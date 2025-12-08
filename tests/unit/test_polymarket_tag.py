import requests
from src.domain.models import Domain
from src.utils.enums import enum_to_list

slugs = enum_to_list(Domain)
slugs += ["all", "entertainment"]
url = "https://gamma-api.polymarket.com/tags/slug/{slug}"

for slug in slugs:
    print(slug)
    url_with_slug = url.format(slug=slug)
    response = requests.get(url_with_slug)
    print(response.text)

