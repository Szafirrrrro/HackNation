// card.hpp — karta reklamy: wczytanie z JSON i wyciągnięcie artefaktów (przyszłych węzłów grafu).
#pragma once
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <ctime>
#include <optional>
#include <string>
#include <vector>

namespace ftf {

using json = nlohmann::json;
using Vec = std::vector<float>;

// Artefakt = dyskretna wartość, która MOŻE się powtórzyć w innej reklamie.
// W grafie staje się węzłem współdzielonym przez reklamy (krawędź twarda).
struct Artifact {
    std::string kind;   // np. "tracking_id", "domain_hop", "favicon"
    std::string value;  // np. "PX-771001"
    std::string key() const { return kind + "|" + value; }
};

struct Face {
    std::string person;  // etykieta z bazy referencyjnej ("" gdy nierozpoznana)
    float similarity = 0, quality = 0, deepfake = 0;
    Vec embedding;
};

struct Card {
    std::string id, source, url, fetched_at, first_seen, last_seen, status;
    std::vector<std::string> redirect_chain;
    std::string final_domain;
    std::string registrar;
    std::optional<std::time_t> registered;  // data rejestracji domeny (RDAP)
    std::vector<std::string> cert_san;
    std::string ad_text;
    Vec text_emb, clip_emb;
    std::optional<std::uint64_t> phash;
    std::vector<Face> faces;
    std::vector<Artifact> artifacts;  // posortowane, bez duplikatów
    json raw;                         // oryginał — do eksportu i audytu
};

// ---------- pomocnicze ----------
inline std::string str(const json& j, const char* k) {
    return (j.contains(k) && j[k].is_string()) ? j[k].get<std::string>() : std::string{};
}
inline const json& sub(const json& j, const char* k) {
    static const json empty = json::object();
    return (j.contains(k) && j[k].is_object()) ? j[k] : empty;
}
inline Vec vec(const json& j, const char* k) {
    Vec v;
    if (j.contains(k) && j[k].is_array())
        for (auto& x : j[k])
            if (x.is_number()) v.push_back(x.get<float>());
    return v;
}
inline std::vector<std::string> strs(const json& j, const char* k) {
    std::vector<std::string> v;
    if (j.contains(k) && j[k].is_array())
        for (auto& x : j[k])
            if (x.is_string() && !x.get<std::string>().empty()) v.push_back(x.get<std::string>());
    return v;
}
// "2026-11-15T14:12:00Z" -> time_t (UTC)
inline std::optional<std::time_t> parse_iso(const std::string& s) {
    std::tm tm{};
    if (s.size() < 19 || !strptime(s.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) return std::nullopt;
    return timegm(&tm);
}
// Usuwa schemat, ścieżkę, parametry i "www." — węzłem jest domena, nie pełny URL
// (pełne linki mają unikalne parametry śledzące i nigdy by się nie powtórzyły).
inline std::string normalize_domain(std::string s) {
    if (auto p = s.find("://"); p != std::string::npos) s = s.substr(p + 3);
    if (auto p = s.find_first_of("/?#"); p != std::string::npos) s = s.substr(0, p);
    if (s.rfind("www.", 0) == 0) s = s.substr(4);
    for (auto& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}
// Endpoint formularza: zostawiamy host + ścieżkę, ucinamy parametry.
inline std::string normalize_endpoint(std::string s) {
    if (auto p = s.find("://"); p != std::string::npos) s = s.substr(p + 3);
    if (auto p = s.find_first_of("?#"); p != std::string::npos) s = s.substr(0, p);
    return s;
}

inline Card parse_card(const json& j) {
    Card c;
    c.raw = j;
    c.id = str(j, "ad_id");
    const auto& prov = sub(j, "provenance");
    c.source = str(prov, "source");
    c.url = str(prov, "url");
    c.fetched_at = str(prov, "fetched_at");
    c.first_seen = str(j, "first_seen");
    c.last_seen = str(j, "last_seen");
    c.status = str(j, "status");

    const auto& infra = sub(j, "infra");
    const auto& rdap = sub(infra, "rdap");
    const auto& dns = sub(infra, "dns");
    const auto& cert = sub(infra, "cert");
    const auto& fav = sub(infra, "favicon");
    const auto& page = sub(j, "page");
    const auto& trk = sub(page, "tracking_ids");
    const auto& contacts = sub(page, "contacts");
    const auto& text = sub(j, "text");
    const auto& visual = sub(j, "visual");

    auto add = [&](std::string kind, std::string value) {
        if (!value.empty()) c.artifacts.push_back({std::move(kind), std::move(value)});
    };

    // --- infrastruktura ---
    for (auto& d : strs(infra, "redirect_chain")) c.redirect_chain.push_back(normalize_domain(d));
    c.final_domain = normalize_domain(str(infra, "final_domain"));
    if (c.final_domain.empty() && !c.redirect_chain.empty()) c.final_domain = c.redirect_chain.back();
    for (auto& d : c.redirect_chain)
        if (d != c.final_domain) add("domain_hop", d);  // domeny frontowe i pośrednicy
    add("domain_final", c.final_domain);

    c.registrar = str(rdap, "registrar");
    c.registered = parse_iso(str(rdap, "registered"));
    add("registrar", c.registrar);
    for (auto& ns : strs(rdap, "nameservers")) add("nameserver", normalize_domain(ns));
    add("ip", str(dns, "ip"));
    add("asn", str(dns, "asn"));
    add("cert", str(cert, "id"));
    for (auto& d : strs(cert, "san")) c.cert_san.push_back(normalize_domain(d));
    if (fav.contains("mmh3") && fav["mmh3"].is_number_integer())
        add("favicon", std::to_string(fav["mmh3"].get<long long>()));

    // --- strona ---
    add("tracking_id", str(trk, "meta_pixel"));
    add("tracking_id", str(trk, "ga"));
    for (auto& s : strs(page, "script_hashes")) add("script", s);
    add("form_endpoint", normalize_endpoint(str(page, "form_endpoint")));
    for (auto& p : strs(contacts, "phones")) add("phone", p);
    for (auto& t : strs(contacts, "telegram")) add("telegram", t);
    for (auto& w : strs(contacts, "crypto")) add("crypto", w);
    add("template", str(page, "dom_template_hash"));
    add("hidden_text", str(page, "hidden_text_hash"));

    // --- treść i obraz ---
    c.ad_text = str(text, "ad_text");
    for (auto& k : strs(text, "keywords")) add("keyword", k);
    c.text_emb = vec(text, "embedding");
    c.clip_emb = vec(visual, "clip_embedding");
    if (auto ph = str(visual, "phash"); !ph.empty()) c.phash = std::stoull(ph, nullptr, 16);

    // --- twarze ---
    if (j.contains("faces") && j["faces"].is_array())
        for (auto& f : j["faces"]) {
            Face fc;
            fc.person = str(f, "person");
            fc.similarity = f.value("similarity", json(0.0)).is_number() ? f["similarity"].get<float>() : 0.f;
            fc.quality = f.value("quality", 0.0f);
            fc.deepfake = f.value("deepfake_score", 0.0f);
            fc.embedding = vec(f, "embedding");
            add("person", fc.person);
            c.faces.push_back(std::move(fc));
        }

    std::sort(c.artifacts.begin(), c.artifacts.end(),
              [](auto& a, auto& b) { return a.key() < b.key(); });
    c.artifacts.erase(std::unique(c.artifacts.begin(), c.artifacts.end(),
                                  [](auto& a, auto& b) { return a.key() == b.key(); }),
                      c.artifacts.end());
    return c;
}

}  // namespace ftf
