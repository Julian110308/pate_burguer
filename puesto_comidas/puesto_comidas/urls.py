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

# Vista personalizada para el login que fuerza el cierre de sesión previo
def login_limpio(request):
    if request.user.is_authenticated:
        logout(request) # Si ya estaba logueado, lo desloguea automáticamente
    return auth_views.LoginView.as_view(template_name='pedidos/login.html')(request)

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 1. Nuestra ruta personalizada
    path('login/', login_limpio, name='login'),
    
    # 2. ¡LA SOLUCIÓN! Atrapamos la ruta por defecto de Django y la redirigimos a tu login
    path('accounts/login/', login_limpio, name='login_accounts'),
    
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    
    path('', include('pedidos.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)