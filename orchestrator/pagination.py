"""Lists show 20 rows a page; the links keep the other query parameters (filters, other lists' pages)."""
from django.core.paginator import Paginator

PER_PAGE = 20


def paginate(request, items, param='page', per_page=PER_PAGE):
    return with_links(request, Paginator(items, per_page).get_page(request.GET.get(param)), param)


def with_links(request, page, param='page'):
    """Add what the pagination include needs to a page (also one from a ListView)."""
    others = request.GET.copy()
    others.pop(param, None)
    page.param = param
    page.query = others.urlencode() + '&' if others else ''
    return page
