from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.db import transaction
from decimal import Decimal


# ============================================
# USUARIO PERSONALIZADO
# ============================================
class Usuario(AbstractUser):
    ROL_CHOICES = [
        ('admin', 'Administrador'),
        ('mesero', 'Mesero'),
    ]
    rol = models.CharField(max_length=10, choices=ROL_CHOICES, default='mesero')

    def save(self, *args, **kwargs):
        # Si el usuario es superusuario, su rol siempre debe ser 'admin'
        if self.is_superuser and self.rol != 'admin':
            self.rol = 'admin'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"


# ============================================
# MENÚ
# ============================================
class Categoria(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name='productos')
    precio = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    disponible = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} - ${self.precio}"


# ============================================
# INGREDIENTES Y PERSONALIZACIÓN
# ============================================
class Ingrediente(models.Model):
    nombre = models.CharField(max_length=50, unique=True)

    class Meta:
        verbose_name = 'Ingrediente'
        verbose_name_plural = 'Ingredientes'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class ProductoIngrediente(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='ingredientes')
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    removible = models.BooleanField(default=True, help_text='Si el cliente puede pedirlo sin este ingrediente')
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'Ingrediente del producto'
        verbose_name_plural = 'Ingredientes del producto'
        ordering = ['orden', 'ingrediente__nombre']
        unique_together = ('producto', 'ingrediente')

    def __str__(self):
        return f"{self.producto.nombre} → {self.ingrediente.nombre} ({'removible' if self.removible else 'fijo'})"


# ============================================
# PEDIDOS
# ============================================
class Pedido(models.Model):
    TIPO_CHOICES = [
        ('mesa', 'Mesa'),
        ('llevar', 'Para llevar'),
    ]
    ESTADO_CHOICES = [
        ('pendiente_pago', 'Pendiente de pago'),
        ('pagado', 'Pagado'),
        ('entregado', 'Entregado'),
        ('anulado', 'Anulado'),
    ]
    METODO_PAGO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('nequi', 'Nequi'),
    ]

    VALOR_ICOPOR = Decimal('1000.00')   # costo de cada caja de icopor (un solo lugar para cambiarlo)
    MAX_CAJAS_ICOPOR = 20               # tope por pedido (evita errores de digitación)

    numero = models.PositiveIntegerField(unique=True, editable=False)
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    numero_mesa = models.PositiveIntegerField(null=True, blank=True)
    mesero = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='pedidos')
    fecha_hora = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente_pago')
    metodo_pago = models.CharField(max_length=10, choices=METODO_PAGO_CHOICES, null=True, blank=True)
    fecha_pago = models.DateTimeField(null=True, blank=True)
    observaciones = models.TextField(blank=True, null=True)
    direccion_entrega = models.CharField(max_length=255, blank=True, null=True)
    editado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_editados')
    fecha_edicion = models.DateTimeField(null=True, blank=True)
    reabierto_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_reabiertos')
    fecha_reapertura = models.DateTimeField(null=True, blank=True)
    cobrar_icopor = models.BooleanField(default=False, help_text="Indica si se añadió el costo del empaque de icopor")
    cantidad_icopor = models.PositiveIntegerField(default=0, help_text="Cajas de icopor del pedido (cada una se cobra aparte)")

    class Meta:
        verbose_name = 'Pedido'
        verbose_name_plural = 'Pedidos'
        ordering = ['-fecha_hora']

    def save(self, *args, **kwargs):
        if not self.numero:
            ultimo = Pedido.objects.order_by('-numero').first()
            self.numero = (ultimo.numero + 1) if ultimo else 1
        super().save(*args, **kwargs)

    @property
    def total(self):
        # Sumamos el subtotal de los productos
        total_productos = sum((d.subtotal for d in self.detalles.all()), Decimal('0.00'))
        
        # Si se cobró el icopor, sumamos su valor
        total_productos += self.valor_icopor

        return total_productos

    @property
    def cajas_icopor(self):
        """Cajas de icopor del pedido. Los pedidos antiguos solo guardaban sí/no, y eso equivale a 1 caja."""
        return self.cantidad_icopor or (1 if self.cobrar_icopor else 0)

    @property
    def valor_icopor(self):
        """Lo que se cobra por todas las cajas de icopor del pedido (0 si no lleva)."""
        return self.VALOR_ICOPOR * self.cajas_icopor

    @staticmethod
    def normalizar_cajas(valor):
        """Convierte lo que llegue (texto, vacío, negativo...) en un número de cajas válido."""
        try:
            cantidad = int(valor)
        except (TypeError, ValueError):
            cantidad = 0
        return min(max(cantidad, 0), Pedido.MAX_CAJAS_ICOPOR)

    def poner_cajas_icopor(self, cantidad):
        """Fija el número de cajas y mantiene sincronizado el campo antiguo (cobrar_icopor)."""
        cantidad = self.normalizar_cajas(cantidad)
        self.cantidad_icopor = cantidad
        self.cobrar_icopor = cantidad > 0

    @property
    def total_productos(self):
        return sum((d.subtotal for d in self.detalles.all()), Decimal('0.00'))

    # ---------- Pagos ----------
    @property
    def total_pagado(self):
        """Suma de todos los pagos registrados para este pedido."""
        return sum((p.monto for p in self.pagos.all()), Decimal('0.00'))

    @property
    def saldo_pendiente(self):
        """Lo que todavía falta por cobrar (nunca negativo): total - pagado."""
        return max(self.total - self.total_pagado, Decimal('0.00'))

    @property
    def metodos_pago_texto(self):
        """Ej.: 'Efectivo' o 'Efectivo + Nequi' si se pagó en varias partes."""
        metodos = []
        for p in self.pagos.all():
            nombre = p.get_metodo_display()
            if nombre not in metodos:
                metodos.append(nombre)
        return ' + '.join(metodos)

    def sincronizar_estado_pago(self):
        """
        Ajusta el estado cuando cambia el total del pedido (se agregan o editan productos):
        - Si estaba pagado/entregado y ahora falta plata -> vuelve a 'pendiente_pago'.
        - Si estaba pendiente, ya tiene pagos y no falta nada -> pasa a 'pagado'.
        Devuelve True si cambió el estado (quien llama debe hacer save()).
        """
        if self.estado in ('pagado', 'entregado') and self.saldo_pendiente > 0:
            self.estado = 'pendiente_pago'
            return True
        if self.estado == 'pendiente_pago' and self.pagos.exists() and self.saldo_pendiente <= 0:
            self.estado = 'pagado'
            return True
        return False

    def __str__(self):
        return f"Pedido #{self.numero} - {self.get_tipo_display()}"

    @property
    def iva_incluido(self):
        """Calcula el IVA incluido en el total (tarifa 19%)."""
        if self.total > 0:
            base = self.total / Decimal('1.19')
            return self.total - base
        return Decimal('0.00')

class Pago(models.Model):
    """Cada cobro real que se le hace a un pedido (un pedido puede tener varios)."""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    metodo = models.CharField(max_length=10, choices=Pedido.METODO_PAGO_CHOICES)
    fecha = models.DateTimeField(default=timezone.now)
    registrado_por = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos_registrados')

    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ['fecha', 'id']

    def __str__(self):
        return f"Pago ${self.monto} ({self.get_metodo_display()}) - Pedido #{self.pedido.numero}"

    @classmethod
    def migrar_pedidos_antiguos(cls):
        """
        Pedidos que se cobraron ANTES de existir este modelo no tienen ningún Pago.
        Aquí se les crea su Pago a partir de metodo_pago / fecha_pago. Es automático,
        seguro de repetir (solo toca pedidos sin pagos) y barato cuando no queda nada por migrar.
        """
        antiguos = Pedido.objects.filter(
            estado__in=['pagado', 'entregado'],
            metodo_pago__in=['efectivo', 'nequi'],
            pagos__isnull=True,
        ).prefetch_related('detalles')

        ids_migrados = []
        for p in antiguos:
            with transaction.atomic():
                if p.pagos.exists():
                    continue
                total = p.total
                if total > 0:
                    cls.objects.create(pedido=p, monto=total, metodo=p.metodo_pago,
                                       fecha=p.fecha_pago or p.fecha_hora)
                    ids_migrados.append(p.id)

        if ids_migrados:
            # Lo adicional de esos pedidos ya estaba cobrado: se quita la marca de "nuevo"
            DetallePedido.objects.filter(pedido_id__in=ids_migrados, es_adicional=True).update(es_adicional=False)


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    observacion = models.TextField(blank=True, null=True)
    fecha_agregado = models.DateTimeField(auto_now_add=True)
    es_adicional = models.BooleanField(default=False)
    ingredientes_quitados = models.ManyToManyField(Ingrediente, through='DetalleIngredienteQuitado', blank=True)

    class Meta:
        verbose_name = 'Detalle del pedido'
        verbose_name_plural = 'Detalles del pedido'

    @property
    def subtotal(self):
        return self.cantidad * self.precio_unitario

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"


class DetalleIngredienteQuitado(models.Model):
    detalle_pedido = models.ForeignKey(DetallePedido, on_delete=models.CASCADE, related_name='ingredientes_quitados_rel')
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.PROTECT)

    class Meta:
        verbose_name = 'Ingrediente quitado'
        verbose_name_plural = 'Ingredientes quitados'
        unique_together = ('detalle_pedido', 'ingrediente')

    def __str__(self):
        return f"Sin {self.ingrediente.nombre}"

class ConfiguracionNegocio(models.Model):
    nombre = models.CharField(max_length=100, default="Pate Burguer")
    direccion = models.CharField(max_length=200, blank=True, null=True)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    logo = models.ImageField(upload_to='configuracion/', blank=True, null=True)
    nit = models.CharField(max_length=20, blank=True, null=True, help_text="NIT con dígito de verificación")
    resolucion_dian = models.CharField(max_length=50, blank=True, null=True, help_text="Número de resolución de facturación")
    prefijo_factura = models.CharField(max_length=10, blank=True, null=True, help_text="Prefijo de la factura POS (ej. PB)")
    rango_inicio = models.PositiveIntegerField(default=1, help_text="Número inicial del rango autorizado")
    rango_fin = models.PositiveIntegerField(default=1000, help_text="Número final del rango autorizado")
    vigencia_dian = models.CharField(max_length=50, blank=True, null=True, help_text="Fecha de vigencia de la resolución (ej. 2026-12-31)")

    class Meta:
        verbose_name = 'Configuración del Negocio'
        verbose_name_plural = 'Configuración del Negocio'

    def __str__(self):
        return self.nombre