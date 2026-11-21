// ftf-graph — silnik łączenia reklam w kampanie (Follow the Fake, HackNation).
//
//   ftf-graph <karty.jsonl> [--out DIR] [--min-cluster N] [--min-samples K] [--min-edge X] [--query AD_ID]
//
// Wejście:  jedna karta reklamy (JSON) na linię.
// Wyjście:  DIR/edges.json, DIR/campaigns.json, DIR/graph.cypher + raport na stdout.
#include "export.hpp"

#include <filesystem>
#include <iostream>

using namespace ftf;

static void usage() {
    std::cerr << "użycie: ftf-graph <karty.jsonl> [--out DIR] [--min-cluster N] [--min-samples K]"
                 " [--min-edge X] [--query AD_ID]\n";
}

int main(int argc, char** argv) {
    if (argc < 2) { usage(); return 1; }
    std::string in = argv[1], out = "out", query;
    Config cfg;
    HdbscanParams prm;
    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) { usage(); std::exit(1); }
            return argv[++i];
        };
        if (a == "--out") out = next();
        else if (a == "--min-cluster") prm.min_cluster_size = std::stoi(next());
        else if (a == "--min-samples") prm.min_samples = std::stoi(next());
        else if (a == "--min-edge") cfg.min_edge = std::stod(next());
        else if (a == "--query") query = next();
        else { usage(); return 1; }
    }

    // 1. wczytanie kart
    std::vector<Card> cards;
    std::ifstream f(in);
    if (!f) { std::cerr << "nie mogę otworzyć " << in << "\n"; return 1; }
    std::string line;
    int ln = 0;
    while (std::getline(f, line)) {
        ++ln;
        if (line.find_first_not_of(" \t\r") == std::string::npos) continue;
        try { cards.push_back(parse_card(json::parse(line))); }
        catch (const std::exception& e) { std::cerr << "linia " << ln << ": pomijam (" << e.what() << ")\n"; }
    }
    std::cout << "Wczytano " << cards.size() << " kart reklam\n";

    // 2. krawędzie z uzasadnieniem  3. klastry  4. eksport
    Scorer sc(cards, cfg);
    auto edges = sc.all_edges();
    auto h = hdbscan(static_cast<int>(cards.size()), edges, prm);
    auto camps = summarize(cards, edges, h, sc);

    std::filesystem::create_directories(out);
    write_json(out, cards, edges, h, camps);
    write_cypher(out + "/graph.cypher", cards, edges, h, camps, sc);

    std::cout << "Krawędzie SIMILAR (score >= " << cfg.min_edge << "): " << edges.size() << "\n"
              << "Kampanie: " << camps.size() << "\n\n";
    for (auto& c : camps) {
        std::cout << "== CMP-" << c.id << "  (" << c.members.size() << " reklam, " << c.alive << " aktywnych / "
                  << c.dead << " martwych, " << c.final_domains.size() << " domen docelowych)\n"
                  << "   okres: " << c.first_seen << " -> " << c.last_seen
                  << "   śr. siła powiązań: " << fmt(c.mean_edge) << "   stabilność: " << fmt(c.stability, 1) << "\n   reklamy:";
        for (int p : c.members) std::cout << " " << cards[p].id;
        std::cout << "\n";
        if (!c.persons.empty()) {
            std::cout << "   wizerunek:";
            for (auto& p : c.persons) std::cout << " " << p;
            std::cout << "\n";
        }
        std::cout << "   wspólne ślady:";
        int shown = 0;
        for (auto& [k, v] : c.shared) {
            if (shown++ == 5) break;
            std::cout << " [" << k << " ×" << v << "]";
        }
        std::cout << "\n\n";
    }
    std::cout << "Bez kampanii:";
    for (size_t p = 0; p < cards.size(); ++p)
        if (h.label[p] < 0) std::cout << " " << cards[p].id;
    std::cout << "\n";

    // 5. tryb analityka: "do czego pasuje ta jedna reklama i dlaczego?"
    if (!query.empty()) {
        int qi = -1;
        for (size_t p = 0; p < cards.size(); ++p)
            if (cards[p].id == query) qi = static_cast<int>(p);
        if (qi < 0) { std::cerr << "brak reklamy " << query << "\n"; return 1; }
        std::cout << "\n### " << query << " -> "
                  << (h.label[qi] < 0 ? std::string("brak kampanii") : "CMP-" + std::to_string(h.label[qi]))
                  << "\n";
        std::vector<const Edge*> mine;
        for (auto& e : edges)
            if (e.a == qi || e.b == qi) mine.push_back(&e);
        std::sort(mine.begin(), mine.end(), [](auto* x, auto* y) { return x->score > y->score; });
        for (size_t i = 0; i < mine.size() && i < 5; ++i) {
            const Edge& e = *mine[i];
            std::cout << "  ~ " << cards[e.a == qi ? e.b : e.a].id << "  score " << fmt(e.score) << "\n";
            for (auto& r : e.reasons)
                std::cout << "      " << (r.hard ? "[TWARDY] " : "[MIĘKKI] ") << "+" << fmt(r.strength) << "  "
                          << r.detail << "\n";
        }
    }
    std::cout << "\nZapisano: " << out << "/edges.json, " << out << "/campaigns.json, " << out << "/graph.cypher\n";
}
