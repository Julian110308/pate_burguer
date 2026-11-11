from functools import wraps
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

def solo_admin(view_func):
    """
    Decorador que verifica que el usuario esté logueado y sea administrador.
    Si no está logueado, lo manda al login.
    Si está logueado pero es mesero:
    - Si es una petición AJAX/API, devuelve un JSON de error 403.
    - Si es una vista normal, lo redirige al menú de mesero.
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        if request.user.rol != 'admin':
            # Detectamos si es una petición de JavaScript (fetch/AJAX) o de nuestra API
            es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
            es_api = request.path.startswith('/api/')
            
            if es_ajax or es_api:
                return JsonResponse({'status': 'error', 'message': 'No autorizado. Se requiere rol de administrador.'}, status=403)
            
            return redirect('menu_mesero')
        return view_func(request, *args, **kwargs)
    return _wrapped_view