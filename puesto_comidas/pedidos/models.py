from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
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
        
        # Si se cobró el icopor, sumamos 1000
        if self.cobrar_icopor:
            total_productos += Decimal('1000.00')
            
        return total_productos

    @property
    def total_productos(self):
        return sum((d.subtotal for d in self.detalles.all()), Decimal('0.00'))
    
    def __str__(self):
        return f"Pedido #{self.numero} - {self.get_tipo_display()}"


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
    nombre = models.CharField(max_length=100, default="La Esquina")
    direccion = models.CharField(max_length=200, blank=True, null=True)
    telefono = models.CharField(max_length=50, blank=True, null=True)
    logo = models.ImageField(upload_to='configuracion/', blank=True, null=True)

    class Meta:
        verbose_name = 'Configuración del Negocio'
        verbose_name_plural = 'Configuración del Negocio'

    def __str__(self):
        return self.nombre