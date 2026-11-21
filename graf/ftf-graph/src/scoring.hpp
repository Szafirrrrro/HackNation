// scoring.hpp — wynik podobieństwa pary reklam z uzasadnieniem.
//
// Intuicja: każdy wspólny ślad to niezależna "szansa", że dwie reklamy mają wspólne źródło.
// Łączymy je jak niezależne zdarzenia (noisy-OR):   score = 1 - Π (1 - s_i)
//   * jeden słaby ślad (0.3)                -> 0.30
//   * dwa średnie (0.5, 0.5)                -> 0.75
//   * cokolwiek + wspólny piksel (0.9)      -> >= 0.90
// Wynik jest zawsze w [0, 1], a każdy składnik s_i trafia do listy uzasadnień krawędzi.
//
// Krawędź TWARDA  = ta sama wartość (wspólny węzeł-artefakt). Siła = waga rodzaju × rzadkość (IDF).
// Krawędź MIĘKKA  = podobieństwo w stopniu 0..1 (wektory, pHash, bliskość dat rejestracji).
#pragma once
#include "card.hpp"

#include <algorithm>
#include <bit>
#include <cmath>
#include <map>
#include <sstream>
#include <unordered_map>

namespace ftf {

struct Config {
    // Bazowa siła wspólnego artefaktu danego rodzaju (zanim uwzględnimy rzadkość).
    std::map<std::string, double> base = {
        {"tracking_id", 0.90},  {"form_endpoint", 0.90}, {"crypto", 0.90},
        {"phone", 0.85},        {"telegram", 0.85},      {"cert", 0.80},
        {"domain_final", 0.75}, {"hidden_text", 0.70},   {"domain_hop", 0.65},
        {"favicon", 0.60},      {"template", 0.60},      {"script", 0.60},
        {"ip", 0.40},           {"nameserver", 0.30},    {"keyword", 0.15},
        {"asn", 0.10},          {"registrar", 0.05},
        {"person", 0.0},  // osoba łączy się MIĘKKO przez embedding twarzy (z wagą jakości)
    };
    double max_df_frac = 0.30;  // artefakt w >30% reklam to "hub" (Cloudflare, Google Fonts) -> ignoruj

    // Progi miękkie: ramp(x, lo, hi) = 0 poniżej lo, 1 powyżej hi, liniowo pomiędzy.
    double w_text = 0.60, text_lo = 0.75, text_hi = 0.95;
    double w_visual = 0.50, vis_lo = 0.80, vis_hi = 0.97;
    double w_phash = 0.60;  int phash_good = 4, phash_bad = 12;  // bity różnicy z 64
    double w_face = 0.50, face_lo = 0.45, face_hi = 0.85;          // × min(jakość) — twarz sama ≤ 0.5
    double w_regburst = 0.50, regburst_window_h = 2.0;             // hurtowa rejestracja domen

    double min_edge = 0.25;  // słabsze krawędzie nie trafiają do grafu
};

struct Reason {
    std::string group;   // grupa dowodu (np. "domain" łączy domain_hop i domain_final)
    std::string kind;
    bool hard = false;
    double strength = 0;
    std::string detail;  // czytelne dla analityka
};

struct Edge {
    int a = 0, b = 0;
    double score = 0;
    std::vector<Reason> reasons;  // posortowane malejąco wg siły
};

inline double ramp(double x, double lo, double hi) {
    return x <= lo ? 0.0 : x >= hi ? 1.0 : (x - lo) / (hi - lo);
}
inline double cosine(const Vec& u, const Vec& v) {
    if (u.empty() || u.size() != v.size()) return 0;
    double d = 0, nu = 0, nv = 0;
    for (size_t i = 0; i < u.size(); ++i) d += u[i] * v[i], nu += u[i] * u[i], nv += v[i] * v[i];
    return (nu == 0 || nv == 0) ? 0 : d / std::sqrt(nu * nv);
}
inline std::string fmt(double x, int prec = 2) {
    std::ostringstream o;
    o.setf(std::ios::fixed);
    o.precision(prec);
    o << x;
    return o.str();
}
inline std::string group_of(const std::string& kind) {
    if (kind == "domain_hop" || kind == "domain_final") return "domain";
    if (kind == "phone" || kind == "telegram" || kind == "crypto") return "contact";
    return kind;
}
inline std::string label_pl(const std::string& kind) {
    static const std::map<std::string, std::string> m = {
        {"tracking_id", "wspólny identyfikator śledzący (piksel/GA)"},
        {"form_endpoint", "formularz wysyła dane pod ten sam adres"},
        {"crypto", "ten sam adres krypto"}, {"phone", "ten sam numer telefonu"},
        {"telegram", "ten sam kontakt Telegram"}, {"cert", "wspólny certyfikat TLS"},
        {"domain_final", "ta sama strona docelowa"}, {"domain_hop", "wspólna domena w łańcuchu przekierowań"},
        {"hidden_text", "ten sam ukryty tekst na stronie"}, {"favicon", "ta sama favicona"},
        {"template", "ten sam szablon strony (DOM)"}, {"script", "ten sam skrypt"},
        {"ip", "ten sam serwer (IP)"}, {"nameserver", "ten sam serwer nazw"},
        {"keyword", "wspólne słowo kluczowe"}, {"asn", "ta sama sieć (ASN)"},
        {"registrar", "ten sam rejestrator"}};
    auto it = m.find(kind);
    return it == m.end() ? kind : it->second;
}

class Scorer {
public:
    Scorer(const std::vector<Card>& cards, Config cfg) : cards_(cards), cfg_(std::move(cfg)) {
        for (auto& c : cards_)
            for (auto& a : c.artifacts) ++df_[a.key()];
    }

    int df(const std::string& key) const {
        auto it = df_.find(key);
        return it == df_.end() ? 0 : it->second;
    }
    // Rzadkość w [0,1]: artefakt w 2 reklamach ~1, w połowie korpusu ~0.
    double rarity(int df) const {
        const double n = static_cast<double>(cards_.size());
        if (df <= 1 || n <= 2 || df > cfg_.max_df_frac * n) return 0;
        return std::log(n / df) / std::log(n / 2.0);
    }

    Edge score(int i, int j) const {
        const Card &A = cards_[i], &B = cards_[j];
        std::vector<Reason> all;

        // --- TWARDE: część wspólna posortowanych list artefaktów ---
        auto ia = A.artifacts.begin(), ib = B.artifacts.begin();
        while (ia != A.artifacts.end() && ib != B.artifacts.end()) {
            const auto ka = ia->key(), kb = ib->key();
            if (ka < kb) { ++ia; continue; }
            if (kb < ka) { ++ib; continue; }
            auto bw = cfg_.base.find(ia->kind);
            const double base = bw == cfg_.base.end() ? 0.2 : bw->second;
            const int d = df(ka);
            const double s = base * rarity(d);
            if (s > 0.005)
                all.push_back({group_of(ia->kind), ia->kind, true, s,
                               label_pl(ia->kind) + ": " + ia->value + " (występuje w " +
                                   std::to_string(d) + " reklamach)"});
            ++ia, ++ib;
        }

        // --- MIĘKKIE ---
        if (double c = cosine(A.text_emb, B.text_emb); c > cfg_.text_lo)
            all.push_back({"text", "text", false, cfg_.w_text * ramp(c, cfg_.text_lo, cfg_.text_hi),
                           "podobna narracja tekstu (cos=" + fmt(c) + ")"});
        if (double c = cosine(A.clip_emb, B.clip_emb); c > cfg_.vis_lo)
            all.push_back({"visual", "visual", false, cfg_.w_visual * ramp(c, cfg_.vis_lo, cfg_.vis_hi),
                           "podobny wygląd reklamy (CLIP cos=" + fmt(c) + ")"});
        if (A.phash && B.phash) {
            const int h = std::popcount(*A.phash ^ *B.phash);
            if (h < cfg_.phash_bad)
                all.push_back({"phash", "phash", false,
                               cfg_.w_phash * (1.0 - ramp(h, cfg_.phash_good, cfg_.phash_bad)),
                               "niemal identyczna grafika (pHash: " + std::to_string(h) + "/64 bitów różnicy)"});
        }
        {   // twarze: najlepsza para, ważona GORSZĄ z dwóch jakości
            double best = 0; std::string det;
            for (auto& fa : A.faces)
                for (auto& fb : B.faces) {
                    const double c = cosine(fa.embedding, fb.embedding);
                    const double q = std::min(fa.quality, fb.quality);
                    const double s = cfg_.w_face * ramp(c, cfg_.face_lo, cfg_.face_hi) * q;
                    if (s > best) {
                        best = s;
                        det = "ta sama twarz" +
                              (fa.person.empty() ? std::string{} : " (" + fa.person + ")") +
                              ", cos=" + fmt(c) + ", jakość min=" + fmt(q);
                    }
                }
            if (best > 0.005) all.push_back({"face", "face", false, best, det});
        }
        if (A.registered && B.registered && !A.registrar.empty() && A.registrar == B.registrar) {
            const double dh = std::abs(std::difftime(*A.registered, *B.registered)) / 3600.0;
            if (dh < cfg_.regburst_window_h)
                all.push_back({"regburst", "regburst", false,
                               cfg_.w_regburst * (1.0 - dh / cfg_.regburst_window_h),
                               "domeny zarejestrowane w odstępie " + fmt(dh * 60, 0) +
                                   " min u " + A.registrar});
        }

        // --- max na grupę (np. 3 wspólne domeny z jednego łańcucha to JEDEN dowód), potem noisy-OR ---
        std::map<std::string, std::pair<Reason, int>> best;
        for (auto& r : all) {
            auto [it, fresh] = best.try_emplace(r.group, r, 0);
            ++it->second.second;
            if (!fresh && r.strength > it->second.first.strength) it->second.first = r;
        }
        Edge e{i, j, 0, {}};
        double keep = 1.0;
        for (auto& [g, rc] : best) {
            Reason r = rc.first;
            if (rc.second > 1) r.detail += " [+" + std::to_string(rc.second - 1) + " podobnych śladów w tej grupie]";
            keep *= (1.0 - r.strength);
            e.reasons.push_back(std::move(r));
        }
        e.score = 1.0 - keep;
        std::sort(e.reasons.begin(), e.reasons.end(),
                  [](auto& x, auto& y) { return x.strength > y.strength; });
        return e;
    }

    // O(N²) par — wystarcza do kilku tysięcy reklam. Przy większej skali: indeks odwrotny
    // artefaktów (twarde) + kNN/FAISS na wektorach (miękkie) zamiast wszystkich par.
    std::vector<Edge> all_edges() const {
        std::vector<Edge> out;
        const int n = static_cast<int>(cards_.size());
        for (int i = 0; i < n; ++i)
            for (int j = i + 1; j < n; ++j)
                if (auto e = score(i, j); e.score >= cfg_.min_edge) out.push_back(std::move(e));
        return out;
    }

    const Config& config() const { return cfg_; }

private:
    const std::vector<Card>& cards_;
    Config cfg_;
    std::unordered_map<std::string, int> df_;
};

}  // namespace ftf
