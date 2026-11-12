from django.urls import path
from . import views
from django.views.generic import TemplateView

urlpatterns = [
    # ==========================================
    # RUTAS PÚBLICAS / DE ENTRADA
    # ==========================================
    path('', views.inicio, name='inicio'),
    path('redireccion/', views.redireccion_por_rol, name='redireccion_por_rol'),

    # ==========================================
    # RUTAS DEL MESERO
    # ==========================================
    path('menu/', views.menu_mesero, name='menu_mesero'),
    path('pedidos-activos/', views.pedidos_activos, name='pedidos_activos'),
    path('pedido/<int:pedido_id>/estado/<str:nuevo_estado>/', views.cambiar_estado_pedido, name='cambiar_estado_pedido'),
    path('pedido/<int:pedido_id>/agregar/', views.agregar_a_pedido, name='agregar_a_pedido'),
    path('ticket/<int:pedido_id>/', views.ver_ticket, name='ver_ticket'),
    path('ticket-cocina/<int:pedido_id>/', views.ver_ticket_cocina, name='ver_ticket_cocina'),

    # ==========================================
    # RUTAS DEL ADMINISTRADOR (Protegidas con @solo_admin)
    # ==========================================
    path('dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('reporte/', views.reporte_diario, name='reporte_diario'),
    
    # Menú y Productos
    path('admin-productos/', views.lista_productos, name='lista_productos'),
    path('admin-productos/nuevo/', views.crear_producto_completo, name='crear_producto_completo'),
    path('admin-productos/<int:producto_id>/editar/', views.editar_producto_completo, name='editar_producto_completo'),
    
    # Personal
    path('admin-usuarios/', views.lista_usuarios, name='lista_usuarios'),
    
    # Historial y Pedidos
    path('admin-historial/', views.historial_pedidos, name='historial_pedidos'),
    path('pedido/<int:pedido_id>/editar/', views.editar_pedido, name='editar_pedido'),
    
    # Configuración e Inventario
    path('admin-configuracion/', views.configuracion_negocio, name='configuracion_negocio'),
    path('admin-inventario/', views.inventario_ventas, name='inventario_ventas'),

    # ==========================================
    # APIS AJAX (Mantienen su estructura JSON)
    # ==========================================
    path('api/crear-ingrediente/', views.crear_ingrediente_ajax, name='crear_ingrediente_ajax'),
    path('api/validar-usuario/', views.validar_usuario_ajax, name='validar_usuario_ajax'),
    path('api/toggle-producto/', views.toggle_estado_producto_ajax, name='toggle_estado_producto_ajax'),

    path('legal/privacidad/', TemplateView.as_view(template_name='pedidos/legal_privacidad.html'), name='politica_privacidad'),
    path('legal/terminos/', TemplateView.as_view(template_name='pedidos/legal_terminos.html'), name='terminos_uso'),
]