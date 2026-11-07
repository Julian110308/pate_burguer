from django.shortcuts import redirect, render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q, F
from django.forms import inlineformset_factory
from django.db import transaction
from django import forms
from django.contrib import messages
from datetime import timedelta
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.core.paginator import Paginator
import json

from .models import (
    Usuario, Categoria, Producto, Ingrediente, 
    Pedido, DetallePedido, DetalleIngredienteQuitado,
    ProductoIngrediente, ConfiguracionNegocio
)

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
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            tipo = data.get('tipo')
            numero_mesa = data.get('numero_mesa')
            observaciones = data.get('observaciones', '')
            carrito = data.get('carrito', [])

            if not carrito:
                return JsonResponse({'status': 'error', 'message': 'El carrito está vacío'}, status=400)

            pedido = Pedido.objects.create(
                tipo=tipo,
                numero_mesa=numero_mesa if tipo == 'mesa' else None,
                mesero=request.user,
                observaciones=observaciones,
                direccion_entrega=data.get('direccion', ''),
                cobrar_icopor=data.get('cobrar_icopor', False)
            )

            for item in carrito:
                producto = Producto.objects.get(id=item['id'])
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
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    productos = Producto.objects.filter(disponible=True).prefetch_related('ingredientes__ingrediente')
    categorias = Categoria.objects.all()
    
    context = {
        'productos': productos,
        'categorias': categorias
    }
    return render(request, 'pedidos/menu_mesero.html', context)

@login_required
def pedidos_activos(request):
    # Traemos todos los pedidos que no estén entregados ni anulados
    pedidos = Pedido.objects.exclude(estado__in=['entregado', 'anulado']).order_by('-fecha_hora')
    
    # Contadores para las tarjetas superiores
    pendientes_pago = pedidos.filter(estado='pendiente_pago').count()
    pagados = pedidos.filter(estado='pagado').count()
    
    # Dinero total pendiente por cobrar (solo los pendientes_pago)
    total_cobrar = sum(p.total for p in pedidos.filter(estado='pendiente_pago'))

    context = {
        'pedidos': pedidos,
        'total_abiertos': pedidos.count(),
        'en_cocina': pendientes_pago, # Los pendientes de pago están en cocina
        'por_cobrar': pagados, # Los pagados están listos para entregar/cobrar
        'total_cobrar': total_cobrar
    }
    return render(request, 'pedidos/pedidos_activos.html', context)

@login_required
def cambiar_estado_pedido(request, pedido_id, nuevo_estado):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    
    if request.method == 'POST':
        if nuevo_estado == 'pagado':
            metodo = request.POST.get('metodo_pago')
            if metodo in ['efectivo', 'nequi']:
                pedido.estado = 'pagado'
                pedido.metodo_pago = metodo
                pedido.fecha_pago = timezone.now()
                pedido.save()
                messages.success(request, f"Pedido #{pedido.numero} marcado como pagado.")
        elif nuevo_estado == 'entregado':
            pedido.estado = 'entregado'
            pedido.save()
            messages.success(request, f"Pedido #{pedido.numero} entregado con éxito.")
            return redirect('pedidos_activos') # <-- Redirección inmediata
        elif nuevo_estado == 'anulado':
            pedido.estado = 'anulado'
            pedido.save()
            messages.success(request, f"Pedido #{pedido.numero} anulado.")
            
        return redirect('pedidos_activos')
        
    return render(request, 'pedidos/cambiar_estado.html', {'pedido': pedido, 'nuevo_estado': nuevo_estado})

@login_required
@xframe_options_sameorigin  # <-- ESTO PERMITE CARGAR EL TICKET EN UN IFRAME
def ver_ticket(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    detalles = pedido.detalles.all()
    config, created = ConfiguracionNegocio.objects.get_or_create(id=1)
    return render(request, 'pedidos/ticket.html', {'pedido': pedido, 'detalles': detalles, 'config': config})

@login_required
def agregar_a_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    
    if pedido.estado != 'pendiente_pago':
        return redirect('pedidos_activos')

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            carrito = data.get('carrito', [])
            
            for item in carrito:
                producto = Producto.objects.get(id=item['id'])
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
            return JsonResponse({'status': 'ok', 'pedido_id': pedido.id})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    productos = Producto.objects.filter(disponible=True).prefetch_related('ingredientes__ingrediente')
    categorias = Categoria.objects.all()
    
    context = {
        'productos': productos,
        'categorias': categorias,
        'pedido': pedido,
        'es_adicional': True
    }
    return render(request, 'pedidos/menu_mesero.html', context)


# ==========================================
# VISTAS DEL ADMINISTRADOR
# ==========================================

@login_required
def dashboard_admin(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
        
    hoy = timezone.localdate()
    pedidos_hoy = Pedido.objects.filter(fecha_hora__date=hoy)
    pedidos_pagados = pedidos_hoy.filter(estado__in=['pagado', 'entregado'])
    
    total_recaudado = sum(p.total for p in pedidos_pagados)
    
    # Traemos los pedidos activos (pendientes de pago o pagados pero no entregados)
    pedidos_activos = Pedido.objects.exclude(estado__in=['entregado', 'anulado']).order_by('-fecha_hora')
    pendientes_count = pedidos_activos.count()
    
    total_productos = Producto.objects.count()
    
    context = {
        'total_recaudado': total_recaudado,
        'pedidos_hoy_count': pedidos_hoy.count(),
        'pendientes': pendientes_count, # Usamos el conteo real
        'total_productos': total_productos,
        'fecha_hoy': hoy,
        'pedidos_activos': pedidos_activos[:5] # Solo mostramos los 5 más recientes en el dashboard para no saturar
    }
    return render(request, 'pedidos/dashboard_admin.html', context)

@login_required
def lista_productos(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        prod_id = request.POST.get('id')
        
        # 1. Lógica para el botón de Activar/Desactivar (El interruptor de "En el menú")
        if accion == 'toggle_estado':
            producto = get_object_or_404(Producto, id=prod_id)
            producto.disponible = not producto.disponible 
            producto.save()
            return redirect('lista_productos')
            
        # 2. Lógica para Crear Categoría desde el modal
        elif accion == 'crear_categoria':
            nombre_cat = request.POST.get('nombre_categoria', '').strip()
            if nombre_cat:
                Categoria.objects.get_or_create(nombre__iexact=nombre_cat, defaults={'nombre': nombre_cat})
            return redirect('lista_productos')

    # --- LÓGICA DE VISUALIZACIÓN (GET) ---
    productos = Producto.objects.all().order_by('nombre')
    categorias = Categoria.objects.all().order_by('nombre')
    
    # KPIs para las tarjetas superiores
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

@login_required
def crear_producto_completo(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    # Creamos el formulario dinámico para los ingredientes con estilos de Bootstrap
    ProductoIngredienteFormSet = inlineformset_factory(
        Producto, 
        ProductoIngrediente, 
        fields=('ingrediente', 'removible', 'orden'),
        extra=1,
        can_delete=True,
        widgets={
            'ingrediente': forms.Select(attrs={'class': 'form-select bg-white border'}),
            'removible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.HiddenInput(), # Ocultamos el orden para que no lo vea el usuario
        }
    )

    if request.method == 'POST':
        categoria_id = request.POST.get('categoria')
        categoria = get_object_or_404(Categoria, id=categoria_id)
        
        producto = Producto(
            nombre=request.POST.get('nombre'),
            precio=request.POST.get('precio'),
            descripcion=request.POST.get('descripcion'),
            categoria=categoria,
            disponible=request.POST.get('disponible') == 'on'
        )
        
        if request.FILES.get('imagen'):
            producto.imagen = request.FILES.get('imagen')

        # Todo o nada: si el formset es inválido no queda un producto huérfano
        with transaction.atomic():
            producto.save()
            formset = ProductoIngredienteFormSet(request.POST, instance=producto)
            if formset.is_valid():
                formset.save()
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

@login_required
def editar_producto_completo(request, producto_id):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    producto = get_object_or_404(Producto, id=producto_id)
    
    # Creamos el formulario dinámico para los ingredientes con estilos de Bootstrap
    ProductoIngredienteFormSet = inlineformset_factory(
        Producto, 
        ProductoIngrediente, 
        fields=('ingrediente', 'removible', 'orden'),
        extra=1,
        can_delete=True,
        widgets={
            'ingrediente': forms.Select(attrs={'class': 'form-select bg-white border'}),
            'removible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'orden': forms.HiddenInput(), # Ocultamos el orden para que no lo vea el usuario
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

        # Todo o nada: si el formset es inválido no se guarda ningún cambio
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

@login_required
def lista_usuarios(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        # 1. CREAR USUARIO
        if accion == 'crear':
            username = request.POST.get('username')
            password = request.POST.get('password')
            first_name = request.POST.get('first_name')
            rol = request.POST.get('rol')
            
            # --- VALIDACIONES DE SEGURIDAD ---
            if not password or len(password) < 8:
                messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
                return redirect('lista_usuarios')
                
            if password.isdigit():
                messages.error(request, "La contraseña no puede ser solo números. Combina letras y números.")
                return redirect('lista_usuarios')
                
            if password.lower() in ['12345678', 'password', 'mesero123', 'contraseña', 'admin1234']:
                messages.error(request, "La contraseña es demasiado débil o común. Elige otra.")
                return redirect('lista_usuarios')
            # ---------------------------------

            if username and password:
                usuario_existente = Usuario.objects.filter(username__iexact=username).first()
                
                if usuario_existente:
                    if usuario_existente.is_active:
                        messages.error(request, f"El nombre de usuario '@{username}' ya está en uso. Por favor, elige otro.")
                    else:
                        usuario_existente.first_name = first_name
                        usuario_existente.rol = rol
                        usuario_existente.set_password(password)
                        usuario_existente.is_active = True
                        usuario_existente.save()
                        messages.success(request, f"El mesero '@{username}' ha sido reactivado exitosamente.")
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
            
        # 2. EDITAR USUARIO
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
            
        # 3. DESACTIVAR USUARIO
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
            
        # 4. RESTABLECER CONTRASEÑA
        elif accion == 'reset_password':
            user_id = request.POST.get('id')
            nueva_password = request.POST.get('nueva_password')
            
            usuario = get_object_or_404(Usuario, id=user_id)
            
            if nueva_password and len(nueva_password) >= 8:
                usuario.set_password(nueva_password)
                usuario.save()
                messages.success(request, f"Contraseña de @{usuario.username} restablecida correctamente.")
            else:
                messages.error(request, "La contraseña debe tener al menos 8 caracteres.")
                
            return redirect('lista_usuarios')

    # --- LÓGICA DE VISUALIZACIÓN (GET) ---
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

@login_required
def reporte_diario(request):
    if request.user.rol != 'admin':
        return redirect('menu_mesero')

    fecha_str = request.GET.get('fecha')
    if fecha_str:
        try:
            fecha_filtro = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha_filtro = timezone.localdate()
    else:
        fecha_filtro = timezone.localdate()

    pedidos_dia = Pedido.objects.filter(fecha_hora__date=fecha_filtro)
    pedidos_cobrados = pedidos_dia.filter(estado__in=['pagado', 'entregado'])
    
    total_efectivo = sum(p.total for p in pedidos_cobrados if p.metodo_pago == 'efectivo')
    total_nequi = sum(p.total for p in pedidos_cobrados if p.metodo_pago == 'nequi')
    total_general = total_efectivo + total_nequi

    pedidos_pendientes = pedidos_dia.filter(estado='pendiente_pago')
    total_pendientes = sum(p.total for p in pedidos_pendientes)

    detalles_cobrados = DetallePedido.objects.filter(pedido__in=pedidos_cobrados)
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


@login_required
def editar_pedido(request, pedido_id):
    if request.user.rol != 'admin':
        return redirect('pedidos_activos')
        
    pedido = get_object_or_404(Pedido, id=pedido_id)

    if request.method == 'POST':
        # 1. Verificamos si se eliminó un producto
        eliminar_id = request.POST.get('eliminar_producto')
        if eliminar_id:
            detalle = get_object_or_404(DetallePedido, id=eliminar_id, pedido=pedido)
            detalle.delete()
            messages.success(request, "Producto eliminado del pedido.")
            return redirect('editar_pedido', pedido_id=pedido.id)

        # 2. Procesamos las cantidades y observaciones normales
        for detalle in pedido.detalles.all():
            nueva_cantidad = request.POST.get(f'cantidad_{detalle.id}')
            
            if nueva_cantidad is not None:
                cantidad_int = int(nueva_cantidad)
                # Ya no necesitamos el if cantidad_int == 0
                detalle.cantidad = cantidad_int
                detalle.save()
                    
            nueva_obs = request.POST.get(f'observacion_{detalle.id}')
            if nueva_obs is not None:
                detalle.observacion = nueva_obs
                detalle.save()

        # 3. Auditoría
        pedido.editado_por = request.user
        pedido.fecha_edicion = timezone.now()
        pedido.save()
        
        return redirect('ver_ticket', pedido_id=pedido.id)

    return render(request, 'pedidos/editar_pedido.html', {'pedido': pedido})
@login_required
def crear_ingrediente_ajax(request):
    if request.user.rol != 'admin': 
        return JsonResponse({'status': 'error', 'message': 'No autorizado'}, status=403)
        
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        if nombre:
            # get_or_create evita duplicados (ignora mayúsculas/minúsculas)
            ingrediente, created = Ingrediente.objects.get_or_create(nombre__iexact=nombre, defaults={'nombre': nombre})
            return JsonResponse({'status': 'ok', 'id': ingrediente.id, 'nombre': ingrediente.nombre})
            
    return JsonResponse({'status': 'error', 'message': 'Nombre inválido'}, status=400)

@login_required
def validar_usuario_ajax(request):
    if request.user.rol != 'admin':
        return JsonResponse({'status': 'error', 'message': 'No autorizado'}, status=403)
        
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        
        # Buscamos si el usuario existe
        usuario = Usuario.objects.filter(username__iexact=username).first()
        
        if usuario:
            if usuario.is_active:
                # Si existe y está activo, bloqueamos
                return JsonResponse({'status': 'error', 'message': 'Este nombre de usuario ya está en uso. Elige otro.'})
            else:
                # Si existe pero está inactivo, devolvemos un estado distinto para avisar
                return JsonResponse({'status': 'reciclar', 'message': 'Este usuario estaba inactivo. Se reactivará con la nueva contraseña.'})
                
        return JsonResponse({'status': 'ok', 'message': 'Nombre disponible'})
        
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def historial_pedidos(request):
    if request.user.rol != 'admin': 
        return redirect('menu_mesero')
    
    # 1. Traemos TODOS los pedidos inicialmente
    pedidos_base = Pedido.objects.all().order_by('-fecha_hora')
    
    # 2. Lógica de Filtro por Fecha
    rango = request.GET.get('rango', 'hoy') 
    hoy = timezone.localdate()
    
    if rango == 'hoy':
        pedidos_base = pedidos_base.filter(fecha_hora__date=hoy)
    elif rango == '7dias':
        fecha_hace_7_dias = hoy - timedelta(days=7)
        pedidos_base = pedidos_base.filter(fecha_hora__date__gte=fecha_hace_7_dias)
    elif rango == 'mes':
        pedidos_base = pedidos_base.filter(fecha_hora__year=hoy.year, fecha_hora__month=hoy.month)
    
    # 3. Lógica de Búsqueda
    busqueda = request.GET.get('buscar')
    if busqueda:
        pedidos_base = pedidos_base.filter(
            Q(numero__icontains=busqueda) | 
            Q(mesero__username__icontains=busqueda) |
            Q(numero_mesa__icontains=busqueda)
        )

    # --- CÁLCULO DE MÉTRICAS ---
    pedidos_validos = pedidos_base.filter(estado__in=['pagado', 'entregado'])
    total_ventas = sum(p.total for p in pedidos_validos)
    total_pedidos = pedidos_base.count()

    detalles = DetallePedido.objects.filter(pedido__in=pedidos_validos)
    mas_vendido = detalles.values('producto__nombre').annotate(
        total_vendido=Sum('cantidad')
    ).order_by('-total_vendido').first()

    # 4. PAGINACIÓN: Mostramos 7 pedidos por página
    paginator = Paginator(pedidos_base, 7) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 5. PREPARAMOS LOS DATOS PARA EL JAVASCRIPT (Solo los de la página actual)
    pedidos_json = []
    for p in page_obj:
        detalles_lista = []
        for d in p.detalles.all():
            detalles_lista.append({
                'cantidad': d.cantidad,
                'producto': d.producto.nombre,
                'subtotal': f"{d.subtotal:,.0f}".replace(",", "."),
                'observacion': d.observacion
            })
            
        pedidos_json.append({
            'id': p.id,
            'numero': p.numero,
            'tipo': p.tipo,
            'numero_mesa': p.numero_mesa,
            'mesero': p.mesero.username,
            'fecha_hora': timezone.localtime(p.fecha_hora).strftime("%d/%m/%Y %H:%M"),
            'estado': p.estado,
            'get_estado_display': p.get_estado_display(),
            'total': f"{p.total:,.0f}".replace(",", "."),
            'detalles': detalles_lista
        })

    context = {
        'pedidos': page_obj, # Ahora enviamos el objeto paginado, no la lista completa
        'page_obj': page_obj,
        'pedidos_json': pedidos_json,
        'busqueda': busqueda,
        'rango_actual': rango,
        'total_ventas': total_ventas,
        'total_pedidos': total_pedidos,
        'mas_vendido': mas_vendido['producto__nombre'] if mas_vendido else 'N/A',
        'mas_vendido_cant': mas_vendido['total_vendido'] if mas_vendido else 0,
    }
    return render(request, 'pedidos/admin_historial.html', context)

@login_required
def configuracion_negocio(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    # get_or_create nos asegura que siempre haya una configuración base
    config, created = ConfiguracionNegocio.objects.get_or_create(id=1)
    
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

@login_required
def toggle_estado_producto_ajax(request):
    if request.user.rol != 'admin': 
        return JsonResponse({'status': 'error', 'message': 'No autorizado'}, status=403)
        
    if request.method == 'POST':
        prod_id = request.POST.get('id')
        producto = get_object_or_404(Producto, id=prod_id)
        
        # Cambiamos el estado (True a False, False a True)
        producto.disponible = not producto.disponible
        producto.save()
        
        return JsonResponse({'status': 'ok', 'nuevo_estado': producto.disponible})
        
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def inventario_ventas(request):
    if request.user.rol != 'admin': return redirect('menu_mesero')
    
    hoy = timezone.localdate()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    # Traemos TODOS los productos (incluso los que no se han vendido)
    productos = Producto.objects.all()
    
    inventario = []
    total_dinero_hoy = 0
    total_unidades_hoy = 0
    ranking_productos = []

    for p in productos:
        detalles_pagados = DetallePedido.objects.filter(
            producto=p, 
            pedido__estado__in=['pagado', 'entregado']
        )
        
        # 1. Ventas de Hoy
        ventas_hoy = detalles_pagados.filter(pedido__fecha_hora__date=hoy).aggregate(
            cant=Sum('cantidad'), 
            total=Sum(F('cantidad') * F('precio_unitario'))
        )
        cant_hoy = ventas_hoy['cant'] or 0
        dinero_hoy = ventas_hoy['total'] or 0
        
        # 2. Ventas de la Semana
        ventas_semana = detalles_pagados.filter(pedido__fecha_hora__date__gte=inicio_semana).aggregate(cant=Sum('cantidad'))
        cant_semana = ventas_semana['cant'] or 0
        
        # 3. Ventas del Mes
        ventas_mes = detalles_pagados.filter(pedido__fecha_hora__date__gte=inicio_mes).aggregate(
            cant=Sum('cantidad'),
            total=Sum(F('cantidad') * F('precio_unitario'))
        )
        cant_mes = ventas_mes['cant'] or 0
        dinero_mes = ventas_mes['total'] or 0

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
    
    # --- ORDENAMIENTO ---
    ranking_productos.sort(key=lambda x: x['cant_mes'], reverse=True)
    
    for index, prod in enumerate(ranking_productos):
        prod['posicion'] = index + 1
        
    inventario.sort(key=lambda x: (x['cant_mes'], x['producto'].nombre), reverse=True)

    producto_estrella = ranking_productos[0] if ranking_productos else None

    # NUEVO: Traemos todas las categorías para los botones de filtro
    categorias = Categoria.objects.all().order_by('nombre')

    context = {
        'inventario': inventario,
        'total_dinero_hoy': total_dinero_hoy,
        'total_unidades_hoy': total_unidades_hoy,
        'total_pedidos_hoy': total_pedidos_hoy,
        'ranking_productos': ranking_productos[:3], 
        'producto_estrella': producto_estrella,
        'categorias': categorias, # <-- Enviamos las categorías al HTML
    }
    return render(request, 'pedidos/admin_inventario.html', context)