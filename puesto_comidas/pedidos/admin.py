from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Usuario, Categoria, Producto, Ingrediente,
    ProductoIngrediente, Pedido, DetallePedido,
    DetalleIngredienteQuitado, Pago,
)


# ============================================
# USUARIO
# ============================================
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'rol', 'is_staff')
    list_filter = ('rol', 'is_staff', 'is_superuser')
    
    # Esto es lo que hace que aparezca al EDITAR un usuario
    fieldsets = UserAdmin.fieldsets + (
        ('Rol en el sistema', {'fields': ('rol',)}),
    )
    
    # Esto es lo que hace que aparezca al CREAR un usuario
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Rol en el sistema', {'fields': ('rol',)}),
    )


# ============================================
# MENÚ
# ============================================
@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


class ProductoIngredienteInline(admin.TabularInline):
    model = ProductoIngrediente
    extra = 1
    autocomplete_fields = ['ingrediente']


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'categoria', 'precio', 'disponible', 'imagen')
    list_filter = ('categoria', 'disponible')
    search_fields = ('nombre', 'descripcion')
    inlines = [ProductoIngredienteInline]
    fieldsets = (
        ('Información básica', {
            'fields': ('nombre', 'descripcion', 'categoria', 'precio')
        }),
        ('Imagen y disponibilidad', {
            'fields': ('imagen', 'disponible')
        }),
    )


@admin.register(Ingrediente)
class IngredienteAdmin(admin.ModelAdmin):
    list_display = ('nombre',)
    search_fields = ('nombre',)


# ============================================
# PEDIDOS
# ============================================
class DetalleIngredienteQuitadoInline(admin.TabularInline):
    model = DetalleIngredienteQuitado
    extra = 0
    autocomplete_fields = ['ingrediente']


class DetallePedidoInline(admin.TabularInline):
    model = DetallePedido
    extra = 0
    readonly_fields = ('fecha_agregado',)
    fields = ('producto', 'cantidad', 'precio_unitario', 'observacion', 'es_adicional', 'fecha_agregado')


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    fields = ('monto', 'metodo', 'fecha', 'registrado_por')
    readonly_fields = ('registrado_por',)


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('numero', 'tipo', 'numero_mesa', 'mesero', 'estado', 'metodo_pago', 'fecha_hora', 'total_mostrado')
    list_filter = ('tipo', 'estado', 'metodo_pago', 'fecha_hora')
    search_fields = ('numero', 'numero_mesa', 'mesero__username')
    readonly_fields = ('numero', 'fecha_hora', 'fecha_pago', 'fecha_edicion', 'fecha_reapertura')
    inlines = [DetallePedidoInline, PagoInline]
    fieldsets = (
        ('Información del pedido', {
            'fields': ('numero', 'tipo', 'numero_mesa', 'mesero', 'estado')
        }),
        ('Pago', {
            'fields': ('metodo_pago', 'fecha_pago')
        }),
        ('Observaciones', {
            'fields': ('observaciones',)
        }),
        ('Auditoría', {
            'fields': ('fecha_hora', 'editado_por', 'fecha_edicion', 'reabierto_por', 'fecha_reapertura'),
            'classes': ('collapse',)
        }),
    )

    def total_mostrado(self, obj):
        return f"${obj.total}"
    total_mostrado.short_description = 'Total'