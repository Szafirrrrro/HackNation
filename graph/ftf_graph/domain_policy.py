"""Shared exclusions: popularity never makes user content trustworthy."""

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
