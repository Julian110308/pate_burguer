from decimal import Decimal
from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q, F, Count
from django.forms import inlineformset_factory
from django.db import transaction
from django import forms
from django.contrib import messages
from datetime import timedelta
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.core.paginator import Paginator
import json
import logging # <-- IMPORTANTE: Para registrar errores de forma segura

# ✅ IMPORTAMOS EL NUEVO DECORADOR
from .decorators import solo_admin

from .models import (
    Usuario, Categoria, Producto, Ingrediente, 
    Pedido, DetallePedido, DetalleIngredienteQuitado,
    ProductoIngrediente, ConfiguracionNegocio, Pago
)

# Inicializamos el logger para errores internos
logger = logging.getLogger(__name__)

def inicio(request):
    return redirect('login')

@login_required
def redireccion_por_rol(request):
    if request.user.rol == 'admin':
        return redirect('dashboard_admin')
    else:
        return redirect('menu_mesero')


# ==========================================
# VISTAS DEL MESERO
# ==========================================

@login_required
def menu_mesero(request):
    # SEGURIDAD: Evitar que el administrador entre a la vista de tomar pedidos
    if request.user.rol == 'admin':
        messages.info(request, "Como administrador, usa el panel para gestionar el sistema.")
        return redirect('dashboard_admin')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            tipo = data.get('tipo')
            numero_mesa = data.get('numero_mesa')
            observaciones = data.get('observaciones', '')
            carrito = data.get('carrito', [])

            if not carrito:
                return JsonResponse({'status': 'error', 'message': 'El carrito está vacío'}, status=400)

            cajas = 0
            if tipo == 'llevar':
                cajas = Pedido.normalizar_cajas(data.get('cantidad_icopor', 1 if data.get('cobrar_icopor') else 0))

            with transaction.atomic():
                pedido = Pedido.objects.create(
                    tipo=tipo,
                    numero_mesa=numero_mesa if tipo == 'mesa' else None,
                    mesero=request.user,
                    observaciones=observaciones,
                    direccion_entrega=data.get('direccion', ''),
                    cobrar_icopor=cajas > 0,
                    cantidad_icopor=cajas,
                )

                for item in carrito:
                    producto = get_object_or_404(Producto, id=item['id'])
                    detalle = DetallePedido.objects.create(
                        pedido=pedido,
                        producto=producto,
                        cantidad=item['cantidad'],
                        precio_unitario=producto.precio,
                        observacion=item.get('observacion', '')
                    )

                    for ing_id in item.get('ingredientes_quitados', []):
                        DetalleIngredienteQuitado.objects.create(
                            detalle_pedido=detalle,
                            ingrediente_id=ing_id
                        )

            return JsonResponse({'status': 'ok', 'pedido_id': pedido.id, 'numero': pedido.numero})

        except Exception as e:
            # SEGURIDAD: Registrar el error real en el servidor, no enviarlo al cliente
            logger.error(f"Error al crear pedido: {str(e)}", exc_info=True)
            return JsonResponse({'status': 'error', 'message': 'Ocurrió un error interno al crear el pedido.'}, status=500)

    productos = Producto.objects.filter(disponible=True).prefetch_related('ingredientes__ingrediente')
    categorias = Categoria.objects.all()
    
    context = {
        'productos': productos,
        'categorias': categorias,
        'valor_icopor': Pedido.VALOR_ICOPOR,
    }
    return render(request, 'pedidos/menu_mesero.html', context)

@login_required
def pedidos_activos(request):
    Pago.migrar_pedidos_antiguos()

    MINUTOS_ALERTA = 15
    MINUTOS_TARDE = 30

    pedidos = (
        Pedido.objects
        .exclude(estado__in=['entregado', 'anulado'])
        .select_related('mesero')
        .prefetch_related('detalles__producto', 'pagos')
        .order_by('-fecha_hora')
    )

    ahora = timezone.now()
    pedidos_lista = []
    total_cobrar = Decimal('0.00')
    pendientes_pago = 0
    pagados = 0

    for p in pedidos:
        saldo = p.saldo_pendiente

        if p.estado == 'pendiente_pago':
            pendientes_pago += 1
            total_cobrar += saldo
        elif p.estado == 'pagado':
            pagados += 1

        minutos = max(int((ahora - p.fecha_hora).total_seconds() // 60), 0)
        if minutos >= MINUTOS_TARDE:
            tiempo_clase = 'tarde'
        elif minutos >= MINUTOS_ALERTA:
            tiempo_clase = 'alerta'
        else:
            tiempo_clase = 'ok'

        pedidos_lista.append({
            'pedido': p,
            'saldo_tarjeta': saldo if p.estado == 'pendiente_pago' else p.total,
            'es_adicional': p.total_pagado > 0 and saldo > 0,
            'sin_pagos': p.total_pagado <= 0,
            'minutos': minutos,
            'tiempo_clase': tiempo_clase,
            'tiempo_pct': max(min(int(minutos * 100 / MINUTOS_TARDE), 100), 4),
        })

    context = {
        'pedidos': pedidos_lista,
        'total_abiertos': len(pedidos_lista),
        'pendientes_pago': pendientes_pago,
        'pagados': pagados,
        'total_cobrar': total_cobrar,
    }
    return render(request, 'pedidos/pedidos_activos.html', context)

@login_required
def cambiar_estado_pedido(request, pedido_id, nuevo_estado):
    Pago.migrar_pedidos_antiguos()
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if nuevo_estado == 'anulado':
        if request.user.rol != 'admin':
            messages.error(request, "Solo un administrador puede anular pedidos.")
            return redirect('pedidos_activos')
        if request.method != 'POST':
            return redirect('pedidos_activos')

    # SEGURIDAD (Anti-CSRF por GET): Si es GET y no es la pantalla de cobro, redirigir
    if request.method == 'GET' and nuevo_estado != 'pagado':
        return redirect('pedidos_activos')

    if request.method == 'POST':
        if nuevo_estado == 'pagado':
            metodo = request.POST.get('metodo_pago')
            if pedido.estado == 'anulado':
                messages.error(request, "No se puede cobrar un pedido anulado.")
            elif metodo not in ['efectivo', 'nequi']:
                messages.error(request, "Elige el método de pago (efectivo o Nequi).")
            else:
                with transaction.atomic():
                    pedido = Pedido.objects.select_for_update().get(id=pedido.id)
                    saldo = pedido.saldo_pendiente

                    if saldo > 0:
                        Pago.objects.create(
                            pedido=pedido,
                            monto=saldo,
                            metodo=metodo,
                            registrado_por=request.user,
                        )
                        pedido.metodo_pago = metodo
                        pedido.fecha_pago = timezone.now()
                        mensaje = f"Pedido #{pedido.numero} marcado como pagado."
                    else:
                        mensaje = f"El pedido #{pedido.numero} ya estaba pagado."

                    if pedido.estado == 'pendiente_pago':
                        pedido.estado = 'pagado'
                    pedido.detalles.filter(es_adicional=True).update(es_adicional=False)
                    pedido.save()
                messages.success(request, mensaje)
        elif nuevo_estado == 'entregado':
            pedido.estado = 'entregado'
            pedido.save()
            messages.success(request, f"Pedido #{pedido.numero} entregado con éxito.")
            return redirect('pedidos_activos')
        elif nuevo_estado == 'anulado':
            if pedido.estado == 'entregado':
                messages.error(request, f"El pedido #{pedido.numero} ya fue entregado y no se puede anular.")
            elif pedido.total_pagado > 0:
                messages.error(request, f"El pedido #{pedido.numero} ya tiene pagos registrados y no se puede anular desde aquí.")
            else:
                pedido.estado = 'anulado'
                pedido.save()
                messages.success(request, f"Pedido #{pedido.numero} anulado.")

        return redirect('pedidos_activos')

    total_pagado = pedido.total_pagado
    return render(request, 'pedidos/cambiar_estado.html', {
        'pedido': pedido,
        'nuevo_estado': nuevo_estado,
        'saldo_a_cobrar': pedido.saldo_pendiente,
        'es_adicional': total_pagado > 0,
        'total_pagado': total_pagado,
    })

@login_required
@xframe_options_sameorigin
def ver_ticket(request, pedido_id):
    Pago.migrar_pedidos_antiguos()
    pedido = get_object_or_404(Pedido, id=pedido_id)

    # ✅ SEGURIDAD (IDOR): Validar que el mesero dueño o el admin puedan ver el ticket
    if request.user.rol != 'admin' and pedido.mesero != request.user:
        messages.error(request, "No tienes permiso para ver este ticket.")
        return redirect('pedidos_activos')

    detalles = list(
        pedido.detalles
        .select_related('producto')
        .prefetch_related('ingredientes_quitados_rel__ingrediente')
    )
    config, created = ConfiguracionNegocio.objects.get_or_create(id=1, defaults={'nombre': 'Pate Burguer'})

    pagos = list(pedido.pagos.all())
    total_pagado = sum((p.monto for p in pagos), Decimal('0.00'))
    saldo_pendiente = max(pedido.total - total_pagado, Decimal('0.00'))
    ultimo_pago = pagos[-1] if pagos else None

    for d in detalles:
        d.es_nuevo = bool(ultimo_pago and saldo_pendiente > 0 and d.fecha_agregado > ultimo_pago.fecha)

    context = {
        'pedido': pedido,
        'detalles': detalles,
        'config': config,
        'pagos': pagos,
        'total_pagado': total_pagado,
        'saldo_pendiente': saldo_pendiente,
        'es_adicional': total_pagado > 0 and saldo_pendiente > 0,
    }
    return render(request, 'pedidos/ticket.html', context)

@login_required
@xframe_options_sameorigin
def ver_ticket_cocina(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)

    # Seguridad: Mismo control que el ticket normal
    if request.user.rol != 'admin' and pedido.mesero != request.user:
        messages.error(request, "No tienes permiso para ver esta comanda.")
        return redirect('pedidos_activos')

    detalles = list(
        pedido.detalles
        .select_related('producto')
        .prefetch_related('ingredientes_quitados_rel__ingrediente')
    )

    context = {
        'pedido': pedido,
        'detalles': detalles,
    }
    return render(request, 'pedidos/ticket_cocina.html', context)

@login_required
def agregar_a_pedido(request, pedido_id):
    Pago.migrar_pedidos_antiguos()
    pedido = get_object_or_404(Pedido, id=pedido_id)

    # ✅ SEGURIDAD (IDOR): Validar que solo el dueño o admin puedan modificar
    if request.user.rol != 'admin' and pedido.mesero != request.user:
        messages.error(request, "No tienes permiso para modificar este pedido.")
        return redirect('pedidos_activos')
    
    if pedido.estado == 'anulado':
        messages.error(request, "No se pueden agregar productos a un pedido anulado.")
        return redirect('pedidos_activos')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            carrito = data.get('carrito', [])
            cajas_extra = Pedido.normalizar_cajas(data.get('cantidad_icopor', 0))
            
            with transaction.atomic():
                for item in carrito:
                    producto = get_object_or_404(Producto, id=item['id'])
                    detalle = DetallePedido.objects.create(
                        pedido=pedido,
                        producto=producto,
                        cantidad=item['cantidad'],
                        precio_unitario=producto.precio,
                        observacion=item.get('observacion', ''),
                        es_adicional=True
                    )
                    for ing_id in item.get('ingredientes_quitados', []):
                        DetalleIngredienteQuitado.objects.create(
                            detalle_pedido=detalle,
                            ingrediente_id=ing_id
                        )
                
                if cajas_extra:
                    pedido.poner_cajas_icopor(pedido.cajas_icopor + cajas_extra)
                cambio_de_estado = pedido.sincronizar_estado_pago()
                if cajas_extra or cambio_de_estado:
                    pedido.save()

            return JsonResponse({'status': 'ok', 'pedido_id': pedido.id})
        except Exception as e:
            # SEGURIDAD: Registrar error, no filtrar al cliente
            logger.error(f"Error al agregar productos al pedido #{pedido.id}: {str(e)}", exc_info=True)
            return JsonResponse({'status': 'error', 'message': 'Ocurrió un error interno al agregar productos.'}, status=500)

    productos = Producto.objects.filter(disponible=True).prefetch_related('ingredientes__ingrediente')
    categorias = Categoria.objects.all()
    
    context = {
        'productos': productos,
        'categorias': categorias,
        'pedido': pedido,
        'es_adicional': True,
        'valor_icopor': Pedido.VALOR_ICOPOR,
    }
    return render(request, 'pedidos/menu_mesero.html', context)


# ==========================================
# VISTAS DEL ADMINISTRADOR
# ==========================================

@solo_admin
def dashboard_admin(request):
    Pago.migrar_pedidos_antiguos()
    hoy = timezone.localdate()
    
    # Rangos de fecha para hoy
    inicio_dia = timezone.make_aware(timezone.datetime.combine(hoy, timezone.datetime.min.time()))
    fin_dia = inicio_dia + timedelta(days=1)
    
    pedidos_hoy = Pedido.objects.filter(fecha_hora__gte=inicio_dia, fecha_hora__lt=fin_dia)

    # Recaudado hoy (pagos reales)
    total_recaudado = (
        Pago.objects.filter(fecha__gte=inicio_dia, fecha__lt=fin_dia)
        .exclude(pedido__estado='anulado')
        .aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    )
    
    pedidos_activos = (
        Pedido.objects.exclude(estado__in=['entregado', 'anulado'])
        .select_related('mesero')
        .prefetch_related('detalles', 'pagos')
        .order_by('-fecha_hora')
    )
    activos_count = pedidos_activos.count()
    por_cobrar_count = pedidos_activos.filter(estado='pendiente_pago').count()
    
    total_productos = Producto.objects.count()

    # --- LÓGICA: Rendimiento del Personal ---
    # 1. Traemos todos los meseros activos
    meseros = Usuario.objects.filter(rol='mesero', is_active=True)
    
    # 2. Calculamos los pedidos de hoy para cada uno con una sola consulta
    pedidos_por_mesero_query = Pedido.objects.filter(
        fecha_hora__gte=inicio_dia, 
        fecha_hora__lt=fin_dia,
        mesero__rol='mesero'
    ).values('mesero__id').annotate(total=Count('id'))
    
    pedidos_por_mesero = {item['mesero__id']: item['total'] for item in pedidos_por_mesero_query}

    # 3. Armamos la lista final con nombre y pedidos
    rendimiento_personal = []
    for mesero in meseros:
        rendimiento_personal.append({
            'nombre': mesero.first_name or mesero.username,
            'username': mesero.username,
            'pedidos_hoy': pedidos_por_mesero.get(mesero.id, 0),
            'en_turno': mesero.last_login and timezone.localtime(mesero.last_login).date() == hoy
        })

    # Ordenamos de mayor a menor pedidos para destacar al mejor del día
    rendimiento_personal.sort(key=lambda x: x['pedidos_hoy'], reverse=True)
    total_meseros_activos = len(rendimiento_personal)
    
    context = {
        'total_recaudado': total_recaudado,
        'pedidos_hoy_count': pedidos_hoy.count(),
        'activos': activos_count,
        'por_cobrar': por_cobrar_count,
        'total_productos': total_productos,
        'fecha_hoy': hoy,
        'pedidos_activos': pedidos_activos[:5],
        # Nuevos datos para la tarjeta:
        'rendimiento_personal': rendimiento_personal,
        'total_meseros_activos': total_meseros_activos,
    }
    return render(request, 'pedidos/dashboard_admin.html', context)

@solo_admin
def lista_productos(request):
    if request.method == 'POST':
        accion = request.POST.get('accion')
        prod_id = request.POST.get('id')
        
        if accion == 'toggle_estado':
            producto = get_object_or_404(Producto, id=prod_id)
            producto.disponible = not producto.disponible 
            producto.save()
            return redirect('lista_productos')
            
        elif accion == 'crear_categoria':
            nombre_cat = request.POST.get('nombre_categoria', '').strip()
            if nombre_cat:
                Categoria.objects.get_or_create(nombre__iexact=nombre_cat, defaults={'nombre': nombre_cat})
            return redirect('lista_productos')

    productos = Producto.objects.all().order_by('nombre')
    categorias = Categoria.objects.all().order_by('nombre')
    
    total_productos = productos.count()
    productos_activos = productos.filter(disponible=True).count()
    total_categorias = categorias.count()
    productos_sin_imagen = productos.filter(imagen='').count() + productos.filter(imagen__isnull=True).count()

    context = {
        'productos': productos, 
        'categorias': categorias,
        'total_productos': total_productos,
        'productos_activos': productos_activos,
        'total_categorias': total_categorias,
        'productos_sin_imagen': productos_sin_imagen,
    }
    return render(request, 'pedidos/admin_lista_productos.html', context)

@solo_admin
def crear_producto_completo(request):
    ProductoIngredienteFormSet = inlineformset_factory(
        Producto, 
        ProductoIngrediente, 
        fields=('ingrediente', 'removible', 'orden'),
        extra=1,
        can_delete=True,
        widgets={
            'ingrediente': forms.Select(attrs={'class': 'form-select bg-white border'}),
            'removible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.HiddenInput(),
        }
    )

    if request.method == 'POST':
        categoria_id = request.POST.get('categoria')
        categoria = get_object_or_404(Categoria, id=categoria_id)
        nombre = (request.POST.get('nombre') or '').strip()

        if not nombre:
            messages.error(request, "El plato necesita un nombre.")
            return redirect('crear_producto_completo')

        producto = Producto(
            nombre=nombre,
            precio=request.POST.get('precio'),
            descripcion=request.POST.get('descripcion'),
            categoria=categoria,
            disponible=request.POST.get('disponible') == 'on'
        )
        
        if request.FILES.get('imagen'):
            producto.imagen = request.FILES.get('imagen')

        with transaction.atomic():
            Categoria.objects.select_for_update().get(id=categoria.id)
            if Producto.objects.filter(nombre__iexact=nombre, categoria=categoria).exists():
                messages.warning(request, f"Ya existe un plato llamado «{nombre}» en la categoría {categoria.nombre}.")
                return redirect('lista_productos')

            producto.save()
            formset = ProductoIngredienteFormSet(request.POST, instance=producto)
            if formset.is_valid():
                formset.save()
                messages.success(request, f"Plato «{nombre}» creado.")
                return redirect('lista_productos')
            transaction.set_rollback(True)
    else:
        formset = ProductoIngredienteFormSet()

    todos_los_ingredientes = Ingrediente.objects.all()
    categorias = Categoria.objects.all()

    return render(request, 'pedidos/crear_producto.html', {
        'formset': formset,
        'todos_los_ingredientes': todos_los_ingredientes,
        'categorias': categorias
    })

@solo_admin
def editar_producto_completo(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    
    ProductoIngredienteFormSet = inlineformset_factory(
        Producto, 
        ProductoIngrediente, 
        fields=('ingrediente', 'removible', 'orden'),
        extra=1,
        can_delete=True,
        widgets={
            'ingrediente': forms.Select(attrs={'class': 'form-select bg-white border'}),
            'removible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.HiddenInput(),
        }
    )

    if request.method == 'POST':
        producto.nombre = request.POST.get('nombre')
        producto.precio = request.POST.get('precio')
        producto.descripcion = request.POST.get('descripcion')
        producto.categoria = get_object_or_404(Categoria, id=request.POST.get('categoria'))
        producto.disponible = request.POST.get('disponible') == 'on'
        
        if request.FILES.get('imagen'):
            producto.imagen = request.FILES.get('imagen')

        with transaction.atomic():
            producto.save()
            formset = ProductoIngredienteFormSet(request.POST, instance=producto)
            if formset.is_valid():
                formset.save()
                return redirect('lista_productos')
            transaction.set_rollback(True)
    else:
        formset = ProductoIngredienteFormSet(instance=producto)

    todos_los_ingredientes = Ingrediente.objects.all()
    categorias = Categoria.objects.all()

    return render(request, 'pedidos/editar_producto.html', {
        'producto': producto,
        'formset': formset,
        'todos_los_ingredientes': todos_los_ingredientes,
        'categorias': categorias
    })

@solo_admin
def lista_usuarios(request):
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'crear':
            username = request.POST.get('username')
            password = request.POST.get('password')
            first_name = request.POST.get('first_name')
            rol = request.POST.get('rol')
            
            if not password or len(password) < 8:
                messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
                return redirect('lista_usuarios')
                
            if password.isdigit():
                messages.error(request, "La contraseña no puede ser solo números.")
                return redirect('lista_usuarios')
                
            if password.lower() in ['12345678', 'password', 'mesero123', 'contraseña', 'admin1234']:
                messages.error(request, "La contraseña es demasiado débil.")
                return redirect('lista_usuarios')

            if username and password:
                usuario_existente = Usuario.objects.filter(username__iexact=username).first()
                
                if usuario_existente:
                    if usuario_existente.is_active:
                        messages.error(request, f"El nombre de usuario '@{username}' ya está en uso.")
                    else:
                        usuario_existente.first_name = first_name
                        usuario_existente.rol = rol
                        usuario_existente.set_password(password)
                        usuario_existente.is_active = True
                        usuario_existente.save()
                        messages.success(request, f"El mesero '@{username}' ha sido reactivado.")
                else:
                    nuevo_usuario = Usuario.objects.create_user(
                        username=username, 
                        password=password,
                        first_name=first_name,
                        rol=rol
                    )
                    nuevo_usuario.save()
                    messages.success(request, f"Mesero '@{username}' creado exitosamente.")
                    
            return redirect('lista_usuarios')
            
        elif accion == 'editar':
            user_id = request.POST.get('id')
            usuario = get_object_or_404(Usuario, id=user_id)
            
            if usuario.rol == 'admin' and usuario != request.user:
                messages.error(request, "No tienes permisos para editar a otro Administrador.")
                return redirect('lista_usuarios')
                
            usuario.first_name = request.POST.get('first_name')
            usuario.rol = request.POST.get('rol')
            
            nueva_password = request.POST.get('nueva_password')
            if nueva_password and len(nueva_password) >= 8:
                usuario.set_password(nueva_password)
                
            usuario.save()
            messages.success(request, f"Datos de @{usuario.username} actualizados.")
            return redirect('lista_usuarios')
            
        elif accion == 'eliminar':
            user_id = request.POST.get('id')
            usuario = get_object_or_404(Usuario, id=user_id)
            
            if usuario != request.user and usuario.rol != 'admin':
                usuario.is_active = False
                usuario.save()
                messages.success(request, f"El mesero '@{usuario.username}' ha sido desactivado.")
            else:
                messages.error(request, "No puedes desactivar a un Administrador ni a ti mismo.")
                
            return redirect('lista_usuarios')
            
        elif accion == 'reset_password':
            user_id = request.POST.get('id')
            nueva_password = request.POST.get('nueva_password')
            
            usuario = get_object_or_404(Usuario, id=user_id)
            
            if nueva_password and len(nueva_password) >= 8:
                usuario.set_password(nueva_password)
                usuario.save()
                messages.success(request, f"Contraseña de @{usuario.username} restablecida.")
            else:
                messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
                
            return redirect('lista_usuarios')

    usuarios_base = Usuario.objects.filter(is_superuser=False, is_active=True).order_by('first_name')
    ahora = timezone.localtime(timezone.now())
    hoy = ahora.date()
    usuarios_data = []

    for u in usuarios_base:
        pedidos_hoy = Pedido.objects.filter(mesero=u, fecha_hora__date=hoy)
        total_pedidos_hoy = pedidos_hoy.count()
        
        ultimo_acceso_str = "Nunca"
        en_turno = False
        
        if u.last_login:
            ultimo_login_local = timezone.localtime(u.last_login)
            if ultimo_login_local.date() == hoy:
                ultimo_acceso_str = f"Hoy, {ultimo_login_local.strftime('%H:%M')}"
                en_turno = True 
            elif ultimo_login_local.date() == (hoy - timedelta(days=1)):
                ultimo_acceso_str = f"Ayer, {ultimo_login_local.strftime('%H:%M')}"
            else:
                ultimo_acceso_str = ultimo_login_local.strftime("%d/%m/%Y")
                
        if total_pedidos_hoy > 0:
            en_turno = True

        usuarios_data.append({
            'usuario': u,
            'pedidos_hoy': total_pedidos_hoy,
            'en_turno': en_turno,
            'ultimo_acceso': ultimo_acceso_str,
        })

    total_integrantes = usuarios_base.count()
    total_meseros = usuarios_base.filter(rol='mesero').count()
    total_admins = usuarios_base.filter(rol='admin').count()
    meseros_en_turno = sum(1 for u in usuarios_data if u['en_turno'] and u['usuario'].rol == 'mesero')
    pedidos_totales_hoy = Pedido.objects.filter(fecha_hora__date=hoy).count()

    context = {
        'usuarios_data': usuarios_data,
        'total_integrantes': total_integrantes,
        'total_meseros': total_meseros,
        'total_admins': total_admins,
        'meseros_en_turno': meseros_en_turno,
        'pedidos_totales_hoy': pedidos_totales_hoy,
    }
    return render(request, 'pedidos/admin_lista_usuarios.html', context)

@solo_admin
def reporte_diario(request):
    Pago.migrar_pedidos_antiguos()
    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_filtro = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_filtro = timezone.localdate()
    else:
        fecha_filtro = timezone.localdate()
    
    inicio = timezone.make_aware(timezone.datetime.combine(fecha_filtro, timezone.datetime.min.time()))
    fin = inicio + timedelta(days=1)

    pedidos_dia = Pedido.objects.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)

    pagos_dia = Pago.objects.filter(fecha__gte=inicio, fecha__lt=fin).exclude(pedido__estado='anulado')
    total_efectivo = pagos_dia.filter(metodo='efectivo').aggregate(t=Sum('monto'))['t'] or Decimal('0.00')
    total_nequi = pagos_dia.filter(metodo='nequi').aggregate(t=Sum('monto'))['t'] or Decimal('0.00')
    total_general = total_efectivo + total_nequi

    pedidos_cobrados = Pedido.objects.filter(
        pagos__in=pagos_dia, estado__in=['pagado', 'entregado']
    ).distinct()

    pedidos_pendientes = pedidos_dia.filter(estado='pendiente_pago')
    total_pendientes = sum((p.saldo_pendiente for p in pedidos_pendientes), Decimal('0.00'))

    pedidos_del_dia_cobrados = pedidos_dia.filter(estado__in=['pagado', 'entregado'])
    detalles_cobrados = DetallePedido.objects.filter(pedido__in=pedidos_del_dia_cobrados)
    productos_vendidos = detalles_cobrados.values('producto__nombre').annotate(
        total_cantidad=Sum('cantidad')
    ).order_by('-total_cantidad')[:5]

    context = {
        'fecha_filtro': fecha_filtro,
        'total_general': total_general,
        'total_efectivo': total_efectivo,
        'total_nequi': total_nequi,
        'total_pendientes': total_pendientes,
        'cantidad_pedidos': pedidos_cobrados.count(),
        'productos_vendidos': productos_vendidos,
    }
    return render(request, 'pedidos/reporte_diario.html', context)

@solo_admin
def editar_pedido(request, pedido_id):
    Pago.migrar_pedidos_antiguos()
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if request.method == 'POST':
        eliminar_id = request.POST.get('eliminar_producto')
        if eliminar_id:
            detalle = get_object_or_404(DetallePedido, id=eliminar_id, pedido=pedido)
            detalle.delete()
            if pedido.sincronizar_estado_pago():
                pedido.save()
            messages.success(request, "Producto eliminado del pedido.")
            return redirect('editar_pedido', pedido_id=pedido.id)

        for detalle in pedido.detalles.all():
            nueva_cantidad = request.POST.get(f'cantidad_{detalle.id}')
            if nueva_cantidad is not None:
                detalle.cantidad = int(nueva_cantidad)
                detalle.save()
                    
            nueva_obs = request.POST.get(f'observacion_{detalle.id}')
            if nueva_obs is not None:
                detalle.observacion = nueva_obs
                detalle.save()

        if 'cantidad_icopor' in request.POST:
            pedido.poner_cajas_icopor(request.POST.get('cantidad_icopor'))

        pedido.editado_por = request.user
        pedido.fecha_edicion = timezone.now()
        pedido.sincronizar_estado_pago() 
        pedido.save()
        
        return redirect('ver_ticket', pedido_id=pedido.id)

    return render(request, 'pedidos/editar_pedido.html', {'pedido': pedido, 'valor_icopor': Pedido.VALOR_ICOPOR})

# ==========================================
# VISTAS AJAX (Ahora protegidas con @solo_admin)
# ==========================================

@solo_admin
def crear_ingrediente_ajax(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        if nombre:
            ingrediente, created = Ingrediente.objects.get_or_create(nombre__iexact=nombre, defaults={'nombre': nombre})
            return JsonResponse({'status': 'ok', 'id': ingrediente.id, 'nombre': ingrediente.nombre})
            
    return JsonResponse({'status': 'error', 'message': 'Nombre inválido'}, status=400)

@solo_admin
def validar_usuario_ajax(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        usuario = Usuario.objects.filter(username__iexact=username).first()
        
        if usuario:
            if usuario.is_active:
                return JsonResponse({'status': 'error', 'message': 'Este nombre de usuario ya está en uso. Elige otro.'})
            else:
                return JsonResponse({'status': 'reciclar', 'message': 'Este usuario estaba inactivo. Se reactivará con la nueva contraseña.'})
                
        return JsonResponse({'status': 'ok', 'message': 'Nombre disponible'})
        
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def historial_pedidos(request):
    Pago.migrar_pedidos_antiguos()
    if request.user.rol != 'admin': 
        return redirect('menu_mesero')
    
    pedidos_base = Pedido.objects.all().order_by('-fecha_hora')
    
    rango = request.GET.get('rango', 'hoy') 
    hoy = timezone.localdate()
    
    if rango == 'hoy':
        inicio = timezone.make_aware(timezone.datetime.combine(hoy, timezone.datetime.min.time()))
        fin = inicio + timedelta(days=1)
        pedidos_base = pedidos_base.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
        
    elif rango == '7dias':
        inicio = timezone.make_aware(timezone.datetime.combine(hoy - timedelta(days=7), timezone.datetime.min.time()))
        fin = timezone.make_aware(timezone.datetime.combine(hoy + timedelta(days=1), timezone.datetime.min.time()))
        pedidos_base = pedidos_base.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
        
    elif rango == 'mes':
        primer_dia_mes = hoy.replace(day=1)
        inicio = timezone.make_aware(timezone.datetime.combine(primer_dia_mes, timezone.datetime.min.time()))
        siguiente_mes = (primer_dia_mes + timedelta(days=32)).replace(day=1)
        fin = timezone.make_aware(timezone.datetime.combine(siguiente_mes, timezone.datetime.min.time()))
        pedidos_base = pedidos_base.filter(fecha_hora__gte=inicio, fecha_hora__lt=fin)
    
    busqueda = request.GET.get('buscar')
    if busqueda:
        pedidos_base = pedidos_base.filter(
            Q(numero__icontains=busqueda) | 
            Q(mesero__username__icontains=busqueda) |
            Q(numero_mesa__icontains=busqueda)
        )

    pedidos_validos = pedidos_base.filter(estado__in=['pagado', 'entregado'])
    total_ventas = (
        Pago.objects.filter(pedido__in=pedidos_base)
        .exclude(pedido__estado='anulado')
        .aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    )
    total_pedidos = pedidos_base.count()

    detalles = DetallePedido.objects.filter(pedido__in=pedidos_validos)
    mas_vendido = detalles.values('producto__nombre').annotate(
        total_vendido=Sum('cantidad')
    ).order_by('-total_vendido').first()

    paginator = Paginator(
        pedidos_base.select_related('mesero').prefetch_related('detalles__producto'), 7
    )
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    pedido_seleccionado = None
    ver_id = request.GET.get('ver')
    if ver_id and ver_id.isdigit():
        pedido_seleccionado = (
            Pedido.objects
            .select_related('mesero')
            .prefetch_related('detalles__producto', 'pagos')
            .filter(id=int(ver_id))
            .first()
        )

    context = {
        'pedidos': page_obj,
        'page_obj': page_obj,
        'pedido_seleccionado': pedido_seleccionado,
        'busqueda': busqueda,
        'rango_actual': rango,
        'total_ventas': total_ventas,
        'total_pedidos': total_pedidos,
        'mas_vendido': mas_vendido['producto__nombre'] if mas_vendido else 'N/A',
        'mas_vendido_cant': mas_vendido['total_vendido'] if mas_vendido else 0,
    }
    return render(request, 'pedidos/admin_historial.html', context)

@solo_admin
def configuracion_negocio(request):
    config, created = ConfiguracionNegocio.objects.get_or_create(id=1, defaults={'nombre': 'Pate Burguer'})
    
    if request.method == 'POST':
        config.nombre = request.POST.get('nombre')
        config.direccion = request.POST.get('direccion')
        config.telefono = request.POST.get('telefono')
        
        if request.FILES.get('logo'):
            config.logo = request.FILES.get('logo')
            
        config.save()
        messages.success(request, "Configuración guardada exitosamente.")
        return redirect('configuracion_negocio')

    return render(request, 'pedidos/admin_configuracion.html', {'config': config})

@solo_admin
def toggle_estado_producto_ajax(request):
    if request.method == 'POST':
        prod_id = request.POST.get('id')
        producto = get_object_or_404(Producto, id=prod_id)
        
        producto.disponible = not producto.disponible
        producto.save()
        
        return JsonResponse({'status': 'ok', 'nuevo_estado': producto.disponible})
        
    return JsonResponse({'status': 'error'}, status=400)

@solo_admin
def inventario_ventas(request):
    hoy = timezone.localdate()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    productos = Producto.objects.all().prefetch_related(
        'detallepedido_set__pedido'
    )

    def dia_local(d):
        return timezone.localtime(d.pedido.fecha_hora).date()

    inventario = []
    total_dinero_hoy = 0
    total_unidades_hoy = 0
    ranking_productos = []

    for p in productos:
        detalles_validos = [
            d for d in p.detallepedido_set.all() 
            if d.pedido.estado in ['pagado', 'entregado']
        ]
        
        hoy_detalles = [d for d in detalles_validos if dia_local(d) == hoy]
        cant_hoy = sum(d.cantidad for d in hoy_detalles)
        dinero_hoy = sum(d.subtotal for d in hoy_detalles)
        
        cant_semana = sum(d.cantidad for d in detalles_validos if dia_local(d) >= inicio_semana)
        
        mes_detalles = [d for d in detalles_validos if dia_local(d) >= inicio_mes]
        cant_mes = sum(d.cantidad for d in mes_detalles)
        dinero_mes = sum(d.subtotal for d in mes_detalles)

        total_dinero_hoy += dinero_hoy
        total_unidades_hoy += cant_hoy

        inventario.append({
            'producto': p,
            'cant_hoy': cant_hoy,
            'cant_semana': cant_semana,
            'cant_mes': int(cant_mes),
        })
        
        if cant_mes > 0:
            ranking_productos.append({
                'nombre': p.nombre,
                'categoria': p.categoria.nombre,
                'cant_mes': int(cant_mes),
                'dinero_mes': dinero_mes
            })

    total_pedidos_hoy = Pedido.objects.filter(fecha_hora__date=hoy, estado__in=['pagado', 'entregado']).count()
    
    ranking_productos.sort(key=lambda x: x['cant_mes'], reverse=True)
    for index, prod in enumerate(ranking_productos):
        prod['posicion'] = index + 1
        
    inventario.sort(key=lambda x: (-x['cant_mes'], x['producto'].nombre.lower()))
    sin_ventas_mes = [i['producto'] for i in inventario if i['cant_mes'] == 0 and i['producto'].disponible]
    producto_estrella = ranking_productos[0] if ranking_productos else None
    categorias = Categoria.objects.all().order_by('nombre')

    context = {
        'inventario': inventario,
        'total_dinero_hoy': total_dinero_hoy,
        'total_unidades_hoy': total_unidades_hoy,
        'total_pedidos_hoy': total_pedidos_hoy,
        'ranking_productos': ranking_productos[:3], 
        'sin_ventas_mes': sin_ventas_mes,
        'producto_estrella': producto_estrella,
        'categorias': categorias,
    }
    return render(request, 'pedidos/admin_inventario.html', context)