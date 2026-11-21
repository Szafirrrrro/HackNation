// export.hpp — podsumowanie kampanii, eksport JSON oraz skrypt Cypher dla Neo4j.
// Neo4j nie ma oficjalnego sterownika C++, więc generujemy plik .cypher, który ładuje się
// jednym poleceniem:  cypher-shell -u neo4j -p <hasło> -f out/graph.cypher
#pragma once
#include "hdbscan.hpp"

#include <fstream>
#include <set>

namespace ftf {

struct Campaign {
    int id = 0;
    std::vector<int> members;
    double stability = 0, mean_edge = 0;
    std::string first_seen, last_seen;
    int alive = 0, dead = 0;
    std::set<std::string> sources, final_domains, persons;
    std::vector<std::pair<std::string, int>> shared;  // artefakt -> ile reklam kampanii go ma
};

inline std::vector<Campaign> summarize(const std::vector<Card>& cards, const std::vector<Edge>& edges,
                                       const HdbscanResult& h, const Scorer& sc) {
    std::vector<Campaign> out(h.stability.size());
    for (size_t k = 0; k < out.size(); ++k) out[k].id = static_cast<int>(k), out[k].stability = h.stability[k];
    for (int p = 0; p < static_cast<int>(cards.size()); ++p) {
        if (h.label[p] < 0) continue;
        auto& c = out[h.label[p]];
        const auto& card = cards[p];
        c.members.push_back(p);
        if (c.first_seen.empty() || card.first_seen < c.first_seen) c.first_seen = card.first_seen;
        if (card.last_seen > c.last_seen) c.last_seen = card.last_seen;
        (card.status == "alive" ? c.alive : c.dead)++;
        c.sources.insert(card.source);
        c.final_domains.insert(card.final_domain);
        for (auto& f : card.faces)
            if (!f.person.empty()) c.persons.insert(f.person);
    }
    std::vector<int> cnt(out.size(), 0);
    for (auto& e : edges)
        if (h.label[e.a] >= 0 && h.label[e.a] == h.label[e.b])
            out[h.label[e.a]].mean_edge += e.score, ++cnt[h.label[e.a]];
    for (size_t k = 0; k < out.size(); ++k) {
        if (cnt[k]) out[k].mean_edge /= cnt[k];
        std::map<std::string, int> m;
        for (int p : out[k].members)
            for (auto& a : cards[p].artifacts)
                if (sc.rarity(sc.df(a.key())) > 0) ++m[a.key()];
        for (auto& [key, v] : m)
            if (v >= 2) out[k].shared.push_back({key, v});
        std::sort(out[k].shared.begin(), out[k].shared.end(),
                  [](auto& x, auto& y) { return x.second > y.second; });
    }
    std::sort(out.begin(), out.end(), [](auto& a, auto& b) { return a.members.size() > b.members.size(); });
    return out;
}

inline json reasons_json(const Edge& e) {
    json r = json::array();
    for (auto& x : e.reasons)
        r.push_back({{"kind", x.kind}, {"hard", x.hard}, {"strength", std::round(x.strength * 1000) / 1000},
                     {"detail", x.detail}});
    return r;
}

inline void write_json(const std::string& dir, const std::vector<Card>& cards, const std::vector<Edge>& edges,
                       const HdbscanResult& h, const std::vector<Campaign>& camps) {
    json je = json::array();
    for (auto& e : edges)
        je.push_back({{"a", cards[e.a].id}, {"b", cards[e.b].id},
                      {"score", std::round(e.score * 1000) / 1000}, {"reasons", reasons_json(e)}});
    std::ofstream(dir + "/edges.json") << je.dump(2);

    json jc = json::array();
    for (auto& c : camps) {
        json m = json::array();
        for (int p : c.members) m.push_back({{"ad_id", cards[p].id}, {"strength", std::round(h.strength[p] * 100) / 100}});
        json sh = json::array();
        for (auto& [k, v] : c.shared) sh.push_back({{"artifact", k}, {"ads", v}});
        jc.push_back({{"campaign", "CMP-" + std::to_string(c.id)}, {"size", c.members.size()},
                      {"stability", std::round(c.stability * 10) / 10}, {"mean_edge_score", std::round(c.mean_edge * 1000) / 1000},
                      {"first_seen", c.first_seen}, {"last_seen", c.last_seen}, {"alive", c.alive}, {"dead", c.dead},
                      {"sources", c.sources}, {"final_domains", c.final_domains}, {"persons", c.persons},
                      {"shared_artifacts", sh}, {"members", m}});
    }
    json noise = json::array();
    for (size_t p = 0; p < cards.size(); ++p)
        if (h.label[p] < 0) noise.push_back(cards[p].id);
    std::ofstream(dir + "/campaigns.json") << json{{"campaigns", jc}, {"unassigned", noise}}.dump(2);
}

// ---------- Cypher ----------
inline std::string q(const std::string& s) {  // literał Cypher w apostrofach
    std::string o = "'";
    for (char c : s) {
        if (c == '\\' || c == '\'') o += '\\';
        o += c;
    }
    return o + "'";
}
inline std::string node_label(const std::string& kind) {
    static const std::map<std::string, std::string> m = {
        {"domain_hop", "Domain"}, {"domain_final", "Domain"}, {"registrar", "Registrar"},
        {"nameserver", "Nameserver"}, {"ip", "IP"}, {"asn", "ASN"}, {"cert", "Certificate"},
        {"favicon", "Favicon"}, {"tracking_id", "TrackingID"}, {"script", "Script"},
        {"form_endpoint", "FormEndpoint"}, {"phone", "Phone"}, {"telegram", "Telegram"},
        {"crypto", "CryptoAddress"}, {"template", "Template"}, {"hidden_text", "HiddenText"},
        {"keyword", "Keyword"}, {"person", "Person"}};
    auto it = m.find(kind);
    return it == m.end() ? "Artifact" : it->second;
}

inline void write_cypher(const std::string& path, const std::vector<Card>& cards, const std::vector<Edge>& edges,
                         const HdbscanResult& h, const std::vector<Campaign>& camps, const Scorer& sc) {
    std::ofstream f(path);
    std::set<std::string> labels{"Ad", "Campaign", "Domain"};
    for (auto& c : cards)
        for (auto& a : c.artifacts) labels.insert(node_label(a.kind));
    for (auto& l : labels)
        f << "CREATE CONSTRAINT IF NOT EXISTS FOR (n:" << l << ") REQUIRE n."
          << (l == "Ad" || l == "Campaign" ? "id" : "value") << " IS UNIQUE;\n";

    for (auto& c : cards) {
        f << "MERGE (a:Ad {id:" << q(c.id) << "}) SET a.source=" << q(c.source) << ", a.url=" << q(c.url)
          << ", a.first_seen=" << q(c.first_seen) << ", a.last_seen=" << q(c.last_seen) << ", a.status=" << q(c.status)
          << ", a.text=" << q(c.ad_text) << ";\n";
        for (auto& a : c.artifacts) {
            if (a.kind == "domain_hop" || a.kind == "domain_final") continue;  // domeny niżej, jako ścieżka
            const int d = sc.df(a.key());
            f << "MATCH (a:Ad {id:" << q(c.id) << "}) MERGE (x:" << node_label(a.kind) << " {value:" << q(a.value)
              << "}) SET x.ads=" << d << ", x.rarity=" << fmt(sc.rarity(d), 3) << " MERGE (a)-[:USES {kind:" << q(a.kind)
              << "}]->(x);\n";
        }
        // łańcuch przekierowań jako ścieżka domen
        if (!c.redirect_chain.empty()) {
            f << "MATCH (a:Ad {id:" << q(c.id) << "}) MERGE (d:Domain {value:" << q(c.redirect_chain.front())
              << "}) MERGE (a)-[:STARTS_AT]->(d);\n";
            for (size_t i = 0; i + 1 < c.redirect_chain.size(); ++i)
                f << "MERGE (d1:Domain {value:" << q(c.redirect_chain[i]) << "}) MERGE (d2:Domain {value:"
                  << q(c.redirect_chain[i + 1]) << "}) MERGE (d1)-[:REDIRECTS_TO]->(d2);\n";
        }
        if (!c.final_domain.empty())
            f << "MATCH (a:Ad {id:" << q(c.id) << "}) MERGE (d:Domain {value:" << q(c.final_domain)
              << "}) MERGE (a)-[:LANDS_ON]->(d);\n";
        const std::string cert = str(sub(sub(c.raw, "infra"), "cert"), "id");
        for (auto& s : c.cert_san)
            if (!cert.empty())
                f << "MERGE (x:Certificate {value:" << q(cert) << "}) MERGE (d:Domain {value:" << q(s)
                  << "}) MERGE (x)-[:COVERS]->(d);\n";
    }
    for (auto& e : edges) {
        std::string rs = "[";
        bool hard = false;
        for (size_t i = 0; i < e.reasons.size(); ++i) {
            rs += (i ? "," : "") + q(e.reasons[i].detail + " (+" + fmt(e.reasons[i].strength) + ")");
            hard |= e.reasons[i].hard;
        }
        rs += "]";
        f << "MATCH (a:Ad {id:" << q(cards[e.a].id) << "}), (b:Ad {id:" << q(cards[e.b].id)
          << "}) MERGE (a)-[r:SIMILAR]-(b) SET r.score=" << fmt(e.score, 3) << ", r.has_hard_evidence="
          << (hard ? "true" : "false") << ", r.reasons=" << rs << ";\n";
    }
    for (auto& c : camps) {
        f << "MERGE (k:Campaign {id:" << q("CMP-" + std::to_string(c.id)) << "}) SET k.size=" << c.members.size()
          << ", k.stability=" << fmt(c.stability, 1) << ", k.first_seen=" << q(c.first_seen)
          << ", k.last_seen=" << q(c.last_seen) << ";\n";
        for (int p : c.members)
            f << "MATCH (a:Ad {id:" << q(cards[p].id) << "}), (k:Campaign {id:" << q("CMP-" + std::to_string(c.id))
              << "}) MERGE (a)-[r:IN_CAMPAIGN]->(k) SET r.strength=" << fmt(h.strength[p]) << ";\n";
    }
}

}  // namespace ftf
