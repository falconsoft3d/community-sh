from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def may(context, instance, permission):
    """{% may instance 'operate' as can_operate %}: what the signed-in user may do with the instance."""
    from ..permissions import may as user_may
    request = context.get('request')
    return bool(request and user_may(request.user, instance, permission))
