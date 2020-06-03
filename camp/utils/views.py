from django.http import Http404
from django.shortcuts import redirect
from django.template import loader, TemplateDoesNotExist
from django.views import generic


class PageTemplate(generic.TemplateView):
    def get(self, request, *args, **kwargs):
        # Enforce a trailing slash.
        if not request.path.endswith('/'):
            return redirect('{0}/'.format(request.path), permanent=True)

        # Template names beginning with an underscore are not allowed.
        if request.path.strip('/').split('/')[-1].startswith('_'):
            raise Http404

        # Set the template_name based on the URL path and raise a 404 if it doesn't exist.
        self.template_name = 'pages/{0}.html'.format(request.path.strip('/') or 'index')

        try:
            loader.get_template(self.template_name)
        except TemplateDoesNotExist:
            raise Http404

        return self.render_to_response({})
