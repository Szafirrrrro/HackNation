"""Host policy. Skipping a fetch and using a host as linking evidence are separate decisions.

NEVER_TRUST_BY_RANK and MULTI_TENANT_HOSTS: ranking must not skip fetching these (scheduler).
SHARED_HOSTS: everybody uses them, so the host alone never links two materials (graph).
TENANT_PARENTS: the platform itself is shared, but each subdomain belongs to one user (graph).
"""

# Hosty, którym ranking nigdy nie nadaje zaufania: skracacze i przekierowania (cel jest ukryty),
# formularze, pliki i treści użytkowników na domenach głównych, komunikatory.
NEVER_TRUST_BY_RANK = {
    # skracacze i przekierowania
    "bit.ly", "bitly.com", "t.co", "goo.gl", "tinyurl.com", "cutt.ly", "is.gd", "ow.ly", "lnkd.in", "rebrand.ly",
    "t.ly", "shorturl.at", "tiny.cc", "rb.gy", "amzn.to", "youtu.be", "app.link", "g.page", "translate.google.com",
    "l.facebook.com", "lm.facebook.com", "l.instagram.com",
    # formularze, pliki i treści użytkowników na domenach głównych
    "docs.google.com", "drive.google.com", "forms.gle", "script.google.com", "storage.googleapis.com",
    "storage.cloud.google.com", "drive.usercontent.google.com", "googleusercontent.com", "sites.google.com",
    "forms.office.com", "sharepoint.com", "onedrive.live.com", "1drv.ms", "hsforms.com",
    "dropbox.com", "github.com", "gitlab.com", "pastebin.com", "4shared.com", "mediafire.com", "telegra.ph",
    "medium.com", "filesdl.top", "filesdl.co", "filesdl.in", "filesdl.vip",
    # hosting statyczny i serverless, którego PSL nie dzieli na domeny użytkowników
    "amazonaws.com", "on.aws", "windows.net", "cloudflarestorage.com", "b-cdn.net",
    # kreatory stron i link-in-bio
    "wix.com", "weebly.com", "jimdo.com", "square.site", "canva.site", "canva.com", "linkr.bio", "heylink.me",
    "mystrikingly.com", "tilda.ws", "tilda.cc", "tilda.ru", "business.site",
    # komunikatory
    "t.me", "telegram.me", "wa.me", "api.whatsapp.com", "chat.whatsapp.com", "m.me", "discord.gg",
    # serwisy społecznościowe i ogłoszeniowe: treść publikuje dowolny użytkownik
    "facebook.com", "fb.watch", "instagram.com", "tiktok.com", "youtube.com", "x.com", "twitter.com",
    "threads.net", "olx.pl", "allegrolokalnie.pl",
}

# Platformy hostingowe / UGC / kreatorzy stron, gdzie wysoka pozycja eTLD+1 w rankingu
# dotyczy samej platformy, a nie pojedynczej strony/subdomeny użytkownika.
MULTI_TENANT_HOSTS = {
    "substack.com",
    "github.io",
    "sites.google.com",
    "vercel.app",
    "myshopify.com",
    "notion.site",
    "webflow.io",
    "pages.dev",
    "herokuapp.com",
    "blogspot.com",
    "wordpress.com",
    "wixsite.com",
    "carrd.co",
    "linktr.ee",
    "beacons.ai",
}

# Platforma jest wspólna, ale subdomena należy do użytkownika i jest jego śladem (oferta.weebly.com).
# Platformy z sekcji prywatnej Public Suffix List rozpoznaje dodatkowo card.is_trusted.
TENANT_PARENTS = MULTI_TENANT_HOSTS | {
    # pliki i hosting: subdomena to bucket, maszyna albo klient
    "amazonaws.com", "amazonaws.com.cn", "s3-accelerate.amazonaws.com", "on.aws", "windows.net",
    "storage.googleapis.com", "bc.googleusercontent.com", "cloudflarestorage.com", "b-cdn.net", "akamaihd.net",
    "cdn77.org", "linodeusercontent.com", "railway.app", "atlassian-dev.net", "quickconnect.to", "mynetname.net",
    # kreatory i publikowanie
    "weebly.com", "jimdo.com", "square.site", "canva.site", "mystrikingly.com", "tilda.ws", "business.site",
    "hostingersite.com", "godaddysites.com", "webnode.page", "squarespace.com", "medium.com",
    "sharepoint.com", "app.link",
    # najemcy pod popularnym rodzicem, których PSL nie wymienia
    "typeform.com", "my.salesforce.com", "vps.ovh.net", "cloud.ovh.net", "crm.dev",
}

# Tylko w tych wildcardach PSL (*.run.app) poziom pod wpisem to wspólny region, a najemca jest niżej.
# W pozostałych (*.eth.limo, *.code.run, tunele) ta etykieta bywa najemcą, więc domyślnie jest śladem.
REGIONAL_WILDCARDS = {
    "digitaloceanspaces.com", "linodeobjects.com", "vultrobjects.com", "run.app", "compute.amazonaws.com",
    "elb.amazonaws.com", "awsapprunner.com", "azurecontainer.io",
}

# Tych domen nie wolno pominąć przy pobieraniu, ale nie są usługą wspólną dla niezależnych reklam.
NOT_SHARED = {"filesdl.top", "filesdl.co", "filesdl.in", "filesdl.vip"}

# Skracacze spoza czołówki rankingu. Tylko dla grafu: polityki schedulera nie zmieniają.
EXTRA_SHORTENERS = {
    "adf.ly", "bit.do", "bitly.ws", "bl.ink", "buff.ly", "clck.ru", "dub.sh", "fb.me", "flip.it", "geni.us",
    "krotki.link", "lnk.bio", "linkin.bio", "qr.ae", "qrco.de", "s.id", "s.shopee.pl", "short.io", "shorte.st",
    "shorturl.com", "skroc.pl", "smarturl.it", "snip.ly", "surl.li", "t2m.io", "tiny.one", "tiny.pl", "trib.al",
    "u.to", "urlz.fr", "v.gd",
}

# Własne usługi platform: dłuższy sufiks wygrywa z regułą najemcy.
PLATFORM_SERVICES = {
    "raw.githubusercontent.com", "avatars.githubusercontent.com", "objects.githubusercontent.com",
    "user-images.githubusercontent.com", "bp.blogspot.com", "login.windows.net", "graph.windows.net",
    "sts.amazonaws.com", "open.substack.com", "miro.medium.com", "cdn-images-1.medium.com",
    "static1.squarespace.com", "assets.squarespace.com", "images.squarespace.com",
    "account.squarespace.com", "login.squarespace.com", "support.squarespace.com",
    "link.medium.com", "help.medium.com", "public-api.wordpress.com", "form.typeform.com",
}

# Wspólny host nie dowodzi wspólnej kampanii: przekierowania, skracacze, serwisy społecznościowe, CDN.
SHARED_HOSTS = (
    (NEVER_TRUST_BY_RANK - TENANT_PARENTS - NOT_SHARED) | EXTRA_SHORTENERS | PLATFORM_SERVICES | {"googleapis.com"}
)
