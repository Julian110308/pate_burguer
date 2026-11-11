"""
URL configuration for puesto_comidas project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.contrib.auth import logout

class LoginRecordarme(auth_views.LoginView):
    """
    Login con el casillero "Recuérdame":
    - Marcado: la sesión dura 30 días en ese dispositivo.
    - Sin marcar: la sesión termina al cerrar el navegador.
    """
    template_name = 'pedidos/login.html'

    def form_valid(self, form):
        respuesta = super().form_valid(form)   # inicia la sesión y prepara la redirección
        if self.request.POST.get('recordarme'):
            self.request.session.set_expiry(60 * 60 * 24 * 30)   # 30 días
        else:
            self.request.session.set_expiry(0)                    # hasta cerrar el navegador
        return respuesta

# Vista personalizada para el login que fuerza el cierre de sesión previo
def login_limpio(request):
    if request.user.is_authenticated:
        logout(request) # Si ya estaba logueado, lo desloguea automáticamente
    return LoginRecordarme.as_view()(request)

urlpatterns = [
    path('gestion-interna-pate-2024/', admin.site.urls),
    
    # 1. Nuestra ruta personalizada
    path('login/', login_limpio, name='login'),
    
    # 2. ¡LA SOLUCIÓN! Atrapamos la ruta por defecto de Django y la redirigimos a tu login
    path('accounts/login/', login_limpio, name='login_accounts'),
    
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    path('', include('pedidos.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)