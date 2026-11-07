from django.urls import path
from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('redireccion/', views.redireccion_por_rol, name='redireccion_por_rol'),
    path('menu/', views.menu_mesero, name='menu_mesero'),
    
    # ruta para el ticket (recibe el ID del pedido)
    path('ticket/<int:pedido_id>/', views.ver_ticket, name='ver_ticket'),

    # rutas para los pedidos activos
    path('pedidos-activos/', views.pedidos_activos, name='pedidos_activos'),
    path('pedido/<int:pedido_id>/estado/<str:nuevo_estado>/', views.cambiar_estado_pedido, name='cambiar_estado_pedido'),

    path('reporte/', views.reporte_diario, name='reporte_diario'),
    path('pedido/<int:pedido_id>/agregar/', views.agregar_a_pedido, name='agregar_a_pedido'),
    path('pedido/<int:pedido_id>/editar/', views.editar_pedido, name='editar_pedido'),
    path('dashboard/', views.dashboard_admin, name='dashboard_admin'),

    # Nuevas rutas de administración custom
    path('admin-productos/', views.lista_productos, name='lista_productos'),
    path('admin-usuarios/', views.lista_usuarios, name='lista_usuarios'),

    path('admin-productos/<int:producto_id>/editar/', views.editar_producto_completo, name='editar_producto_completo'),
    path('admin-productos/nuevo/', views.crear_producto_completo, name='crear_producto_completo'),
    path('api/crear-ingrediente/', views.crear_ingrediente_ajax, name='crear_ingrediente_ajax'),
    path('api/validar-usuario/', views.validar_usuario_ajax, name='validar_usuario_ajax'),

    path('admin-historial/', views.historial_pedidos, name='historial_pedidos'),
    path('admin-configuracion/', views.configuracion_negocio, name='configuracion_negocio'),
    path('api/toggle-producto/', views.toggle_estado_producto_ajax, name='toggle_estado_producto_ajax'),
    path('admin-inventario/', views.inventario_ventas, name='inventario_ventas'),
]