"""The cities NoloRoute can cover: Turkey's 81 province centres, popular Turkish destinations that
are not province centres, and popular cities abroad.

`query` is what Google is searched for to find the city's centre and extent.
"""

from dataclasses import dataclass
from typing import Literal

Kind = Literal["province", "destination", "abroad"]


@dataclass(frozen=True)
class CatalogCity:
    id: str
    name_en: str
    name_tr: str
    kind: Kind
    country: str  # ISO 3166-1 alpha-2
    currency: str
    timezone: str
    query: str


def _tr(id_: str, name_tr: str, name_en: str | None = None, query: str | None = None, kind: Kind = "province"):
    return CatalogCity(
        id_, name_en or name_tr, name_tr, kind, "TR", "TRY", "Europe/Istanbul", query or f"{name_tr}, Türkiye"
    )


def _abroad(id_: str, name_en: str, name_tr: str, country: str, currency: str, timezone: str, query: str):
    return CatalogCity(id_, name_en, name_tr, "abroad", country, currency, timezone, query)


# Plate-code order. The province centre is searched for, not the (often huge) province.
PROVINCES = [
    _tr("adana", "Adana"),
    _tr("adiyaman", "Adıyaman", "Adiyaman"),
    _tr("afyonkarahisar", "Afyonkarahisar"),
    _tr("agri", "Ağrı", "Agri"),
    _tr("amasya", "Amasya"),
    _tr("ankara", "Ankara"),
    _tr("antalya", "Antalya"),
    _tr("artvin", "Artvin"),
    _tr("aydin", "Aydın", "Aydin"),
    _tr("balikesir", "Balıkesir", "Balikesir"),
    _tr("bilecik", "Bilecik"),
    _tr("bingol", "Bingöl", "Bingol"),
    _tr("bitlis", "Bitlis"),
    _tr("bolu", "Bolu"),
    _tr("burdur", "Burdur"),
    _tr("bursa", "Bursa"),
    _tr("canakkale", "Çanakkale", "Canakkale"),
    _tr("cankiri", "Çankırı", "Cankiri"),
    _tr("corum", "Çorum", "Corum"),
    _tr("denizli", "Denizli"),
    _tr("diyarbakir", "Diyarbakır", "Diyarbakir"),
    _tr("edirne", "Edirne"),
    _tr("elazig", "Elazığ", "Elazig"),
    _tr("erzincan", "Erzincan"),
    _tr("erzurum", "Erzurum"),
    _tr("eskisehir", "Eskişehir", "Eskisehir"),
    _tr("gaziantep", "Gaziantep"),
    _tr("giresun", "Giresun"),
    _tr("gumushane", "Gümüşhane", "Gumushane"),
    _tr("hakkari", "Hakkari"),
    _tr("hatay", "Hatay (Antakya)", "Hatay (Antakya)", query="Antakya, Hatay, Türkiye"),
    _tr("isparta", "Isparta"),
    _tr("mersin", "Mersin"),
    _tr("istanbul", "İstanbul", "Istanbul"),
    _tr("izmir", "İzmir", "Izmir"),
    _tr("kars", "Kars"),
    _tr("kastamonu", "Kastamonu"),
    _tr("kayseri", "Kayseri"),
    _tr("kirklareli", "Kırklareli", "Kirklareli"),
    _tr("kirsehir", "Kırşehir", "Kirsehir"),
    _tr("kocaeli", "Kocaeli (İzmit)", "Kocaeli (Izmit)", query="İzmit, Kocaeli, Türkiye"),
    _tr("konya", "Konya"),
    _tr("kutahya", "Kütahya", "Kutahya"),
    _tr("malatya", "Malatya"),
    _tr("manisa", "Manisa"),
    _tr("kahramanmaras", "Kahramanmaraş", "Kahramanmaras"),
    _tr("mardin", "Mardin"),
    _tr("mugla", "Muğla", "Mugla"),
    _tr("mus", "Muş", "Mus"),
    _tr("nevsehir", "Nevşehir", "Nevsehir"),
    _tr("nigde", "Niğde", "Nigde"),
    _tr("ordu", "Ordu"),
    _tr("rize", "Rize"),
    _tr("sakarya", "Sakarya (Adapazarı)", "Sakarya (Adapazari)", query="Adapazarı, Sakarya, Türkiye"),
    _tr("samsun", "Samsun"),
    _tr("siirt", "Siirt"),
    _tr("sinop", "Sinop"),
    _tr("sivas", "Sivas"),
    _tr("tekirdag", "Tekirdağ", "Tekirdag"),
    _tr("tokat", "Tokat"),
    _tr("trabzon", "Trabzon"),
    _tr("tunceli", "Tunceli"),
    _tr("sanliurfa", "Şanlıurfa", "Sanliurfa"),
    _tr("usak", "Uşak", "Usak"),
    _tr("van", "Van"),
    _tr("yozgat", "Yozgat"),
    _tr("zonguldak", "Zonguldak"),
    _tr("aksaray", "Aksaray"),
    _tr("bayburt", "Bayburt"),
    _tr("karaman", "Karaman"),
    _tr("kirikkale", "Kırıkkale", "Kirikkale"),
    _tr("batman", "Batman"),
    _tr("sirnak", "Şırnak", "Sirnak"),
    _tr("bartin", "Bartın", "Bartin"),
    _tr("ardahan", "Ardahan"),
    _tr("igdir", "Iğdır", "Igdir"),
    _tr("yalova", "Yalova"),
    _tr("karabuk", "Karabük", "Karabuk"),
    _tr("kilis", "Kilis"),
    _tr("osmaniye", "Osmaniye"),
    _tr("duzce", "Düzce", "Duzce"),
]

# Where Turkish travellers actually go, but which are not province centres.
DESTINATIONS = [
    _tr("kapadokya", "Kapadokya (Göreme)", "Cappadocia (Göreme)", "Göreme, Nevşehir, Türkiye", "destination"),
    _tr("bodrum", "Bodrum", query="Bodrum, Muğla, Türkiye", kind="destination"),
    _tr("fethiye", "Fethiye", query="Fethiye, Muğla, Türkiye", kind="destination"),
    _tr("marmaris", "Marmaris", query="Marmaris, Muğla, Türkiye", kind="destination"),
    _tr("alanya", "Alanya", query="Alanya, Antalya, Türkiye", kind="destination"),
    _tr("kas", "Kaş", "Kas", "Kaş, Antalya, Türkiye", "destination"),
    _tr("kusadasi", "Kuşadası", "Kusadasi", "Kuşadası, Aydın, Türkiye", "destination"),
    _tr("selcuk", "Selçuk (Efes)", "Selcuk (Ephesus)", "Selçuk, İzmir, Türkiye", "destination"),
    _tr("pamukkale", "Pamukkale", query="Pamukkale, Denizli, Türkiye", kind="destination"),
    _tr("safranbolu", "Safranbolu", query="Safranbolu, Karabük, Türkiye", kind="destination"),
]

ABROAD = [
    _abroad("london", "London", "Londra", "GB", "GBP", "Europe/London", "London, UK"),
    _abroad("rome", "Rome", "Roma", "IT", "EUR", "Europe/Rome", "Rome, Italy"),
    _abroad("barcelona", "Barcelona", "Barselona", "ES", "EUR", "Europe/Madrid", "Barcelona, Spain"),
    _abroad("madrid", "Madrid", "Madrid", "ES", "EUR", "Europe/Madrid", "Madrid, Spain"),
    _abroad("lisbon", "Lisbon", "Lizbon", "PT", "EUR", "Europe/Lisbon", "Lisbon, Portugal"),
    _abroad("amsterdam", "Amsterdam", "Amsterdam", "NL", "EUR", "Europe/Amsterdam", "Amsterdam, Netherlands"),
    _abroad("berlin", "Berlin", "Berlin", "DE", "EUR", "Europe/Berlin", "Berlin, Germany"),
    _abroad("munich", "Munich", "Münih", "DE", "EUR", "Europe/Berlin", "Munich, Germany"),
    _abroad("prague", "Prague", "Prag", "CZ", "CZK", "Europe/Prague", "Prague, Czechia"),
    _abroad("vienna", "Vienna", "Viyana", "AT", "EUR", "Europe/Vienna", "Vienna, Austria"),
    _abroad("budapest", "Budapest", "Budapeşte", "HU", "HUF", "Europe/Budapest", "Budapest, Hungary"),
    _abroad("athens", "Athens", "Atina", "GR", "EUR", "Europe/Athens", "Athens, Greece"),
    _abroad("milan", "Milan", "Milano", "IT", "EUR", "Europe/Rome", "Milan, Italy"),
    _abroad("venice", "Venice", "Venedik", "IT", "EUR", "Europe/Rome", "Venice, Italy"),
    _abroad("florence", "Florence", "Floransa", "IT", "EUR", "Europe/Rome", "Florence, Italy"),
    _abroad("copenhagen", "Copenhagen", "Kopenhag", "DK", "DKK", "Europe/Copenhagen", "Copenhagen, Denmark"),
    _abroad("stockholm", "Stockholm", "Stokholm", "SE", "SEK", "Europe/Stockholm", "Stockholm, Sweden"),
    _abroad("brussels", "Brussels", "Brüksel", "BE", "EUR", "Europe/Brussels", "Brussels, Belgium"),
    _abroad("dubai", "Dubai", "Dubai", "AE", "AED", "Asia/Dubai", "Dubai, United Arab Emirates"),
    _abroad("tbilisi", "Tbilisi", "Tiflis", "GE", "GEL", "Asia/Tbilisi", "Tbilisi, Georgia"),
    _abroad("baku", "Baku", "Bakü", "AZ", "AZN", "Asia/Baku", "Baku, Azerbaijan"),
    _abroad("sarajevo", "Sarajevo", "Saraybosna", "BA", "BAM", "Europe/Sarajevo", "Sarajevo, Bosnia and Herzegovina"),
    _abroad("belgrade", "Belgrade", "Belgrad", "RS", "RSD", "Europe/Belgrade", "Belgrade, Serbia"),
    _abroad("new-york", "New York", "New York", "US", "USD", "America/New_York", "Manhattan, New York, USA"),
    _abroad("tokyo", "Tokyo", "Tokyo", "JP", "JPY", "Asia/Tokyo", "Tokyo, Japan"),
    _abroad("kyoto", "Kyoto", "Kyoto", "JP", "JPY", "Asia/Tokyo", "Kyoto, Japan"),
    _abroad("seoul", "Seoul", "Seul", "KR", "KRW", "Asia/Seoul", "Seoul, South Korea"),
    _abroad("bangkok", "Bangkok", "Bangkok", "TH", "THB", "Asia/Bangkok", "Bangkok, Thailand"),
    _abroad("singapore", "Singapore", "Singapur", "SG", "SGD", "Asia/Singapore", "Singapore"),
    _abroad("marrakech", "Marrakech", "Marakeş", "MA", "MAD", "Africa/Casablanca", "Marrakech, Morocco"),
]

CATALOG = PROVINCES + DESTINATIONS + ABROAD
