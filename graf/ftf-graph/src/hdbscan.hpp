// hdbscan.hpp — HDBSCAN na grafie rzadkim (krawędzie z Scorer), bez macierzy odległości.
//
// Kroki (jak w oryginale Campello et al. 2013, tylko na grafie zamiast na wszystkich parach):
//  1. odległość krawędzi d = 1 - score
//  2. core(p) = d do k-tego najbliższego sąsiada (k = min_samples); gdy sąsiadów < k -> największa d
//  3. odległość "mutual reachability"  m(p,q) = max(core(p), core(q), d(p,q))
//     — gęste grupy zostają gęste, a pojedyncze przypadkowe krawędzie są "rozciągane"
//  4. minimalne drzewo rozpinające (Kruskal) na m  -> hierarchia single-linkage (dendrogram)
//  5. drzewo skondensowane: idąc od góry, podział liczy się tylko gdy OBIE części mają
//     >= min_cluster_size; mniejsze odłamki to punkty "wypadające" z klastra
//  6. stabilność klastra = Σ (λ_wypadnięcia - λ_narodzin), λ = 1/d; wybór EOM:
//     bierz klaster, jeśli jest stabilniejszy niż suma jego dzieci
// Rozłączne składowe grafu to zawsze osobne klastry (brak krawędzi = brak dowodu).
#pragma once
#include "scoring.hpp"

#include <functional>
#include <limits>
#include <numeric>

namespace ftf {

struct HdbscanParams {
    int min_cluster_size = 3;
    int min_samples = 2;
};

struct HdbscanResult {
    std::vector<int> label;        // -1 = szum, inaczej numer kampanii 0..K-1
    std::vector<double> strength;  // 0..1 jak "rdzeniowa" jest reklama w swojej kampanii
    std::vector<double> stability; // stabilność każdej wybranej kampanii
};

class DSU {
public:
    explicit DSU(int n) : p_(n), r_(n, 0) { std::iota(p_.begin(), p_.end(), 0); }
    int find(int x) { return p_[x] == x ? x : p_[x] = find(p_[x]); }
    bool unite(int a, int b) {
        a = find(a), b = find(b);
        if (a == b) return false;
        if (r_[a] < r_[b]) std::swap(a, b);
        p_[b] = a;
        if (r_[a] == r_[b]) ++r_[a];
        return true;
    }
private:
    std::vector<int> p_, r_;
};

inline HdbscanResult hdbscan(int n, const std::vector<Edge>& edges, HdbscanParams prm) {
    constexpr double EPS = 1e-3;
    const double INF = std::numeric_limits<double>::infinity();

    // 1-2. core distance
    std::vector<std::vector<double>> nd(n);
    for (auto& e : edges) {
        const double d = std::max(EPS, 1.0 - e.score);
        nd[e.a].push_back(d), nd[e.b].push_back(d);
    }
    std::vector<double> core(n, INF);
    for (int p = 0; p < n; ++p) {
        auto& v = nd[p];
        if (v.empty()) continue;
        std::sort(v.begin(), v.end());
        core[p] = v[std::min<size_t>(prm.min_samples, v.size()) - 1];
    }
    // 3-4. MST na mutual reachability -> dendrogram
    struct MR { double m; int a, b; };
    std::vector<MR> mr;
    for (auto& e : edges) {
        const double d = std::max(EPS, 1.0 - e.score);
        mr.push_back({std::max({d, core[e.a], core[e.b]}), e.a, e.b});
    }
    std::sort(mr.begin(), mr.end(), [](auto& x, auto& y) { return x.m < y.m; });

    struct Node { int left = -1, right = -1, size = 1; double dist = 0; };
    std::vector<Node> dendro(n);          // 0..n-1 liście (reklamy), dalej węzły wewnętrzne
    std::vector<int> top(n);              // korzeń DSU -> węzeł dendrogramu
    std::iota(top.begin(), top.end(), 0);
    DSU dsu(n);
    for (auto& e : mr) {
        const int ra = dsu.find(e.a), rb = dsu.find(e.b);
        if (ra == rb) continue;
        Node nd2{top[ra], top[rb], dendro[top[ra]].size + dendro[top[rb]].size, e.m};
        dendro.push_back(nd2);
        dsu.unite(ra, rb);
        top[dsu.find(ra)] = static_cast<int>(dendro.size()) - 1;
    }
    std::vector<int> roots;
    for (int p = 0; p < n; ++p)
        if (dsu.find(p) == p) roots.push_back(top[p]);

    // 5. drzewo skondensowane
    std::vector<int> parent{-1};          // klaster 0 = wirtualny korzeń
    std::vector<double> birth{0.0}, stab{0.0};
    std::vector<int> csize{n};
    std::vector<std::vector<int>> kids(1);
    std::vector<int> fell_from(n, 0);     // z którego klastra wypadł punkt
    std::vector<double> fell_lambda(n, 0.0);

    auto leaves = [&](int node, std::vector<int>& out) {
        std::vector<int> st{node};
        while (!st.empty()) {
            const int x = st.back(); st.pop_back();
            if (x < n) out.push_back(x);
            else st.push_back(dendro[x].left), st.push_back(dendro[x].right);
        }
    };
    auto fall = [&](int node, int cl, double lambda) {
        std::vector<int> pts;
        leaves(node, pts);
        for (int p : pts) fell_from[p] = cl, fell_lambda[p] = lambda;
    };
    auto new_cluster = [&](int par, double lambda, int size) {
        parent.push_back(par), birth.push_back(lambda), stab.push_back(0), csize.push_back(size);
        kids.emplace_back();
        kids[par].push_back(static_cast<int>(parent.size()) - 1);
        return static_cast<int>(parent.size()) - 1;
    };

    std::vector<std::pair<int, int>> work;  // (węzeł dendrogramu, klaster)
    for (int r : roots) {
        if (dendro[r].size >= prm.min_cluster_size) work.push_back({r, new_cluster(0, 0.0, dendro[r].size)});
        else fall(r, 0, 0.0);
    }
    while (!work.empty()) {
        auto [node, cl] = work.back();
        work.pop_back();
        if (node < n) { fell_from[node] = cl, fell_lambda[node] = 1.0 / EPS; continue; }
        const Node& x = dendro[node];
        const double lambda = 1.0 / std::max(EPS, x.dist);
        const bool bigL = dendro[x.left].size >= prm.min_cluster_size;
        const bool bigR = dendro[x.right].size >= prm.min_cluster_size;
        if (bigL && bigR) {
            work.push_back({x.left, new_cluster(cl, lambda, dendro[x.left].size)});
            work.push_back({x.right, new_cluster(cl, lambda, dendro[x.right].size)});
        } else if (bigL) { fall(x.right, cl, lambda); work.push_back({x.left, cl}); }
        else if (bigR)   { fall(x.left, cl, lambda);  work.push_back({x.right, cl}); }
        else             { fall(x.left, cl, lambda);  fall(x.right, cl, lambda); }
    }

    // 6. stabilność + wybór EOM (dzieci mają większe numery niż rodzice)
    const int C = static_cast<int>(parent.size());
    for (int p = 0; p < n; ++p) stab[fell_from[p]] += fell_lambda[p] - birth[fell_from[p]];
    for (int c = 1; c < C; ++c) stab[parent[c]] += csize[c] * (birth[c] - birth[parent[c]]);

    std::vector<char> selected(C, 0);
    std::vector<double> best = stab;
    std::function<void(int)> deselect = [&](int c) {
        for (int k : kids[c]) selected[k] = 0, deselect(k);
    };
    for (int c = C - 1; c >= 1; --c) {
        double childsum = 0;
        for (int k : kids[c]) childsum += best[k];
        if (!kids[c].empty() && childsum > stab[c]) best[c] = childsum;
        else { selected[c] = 1; deselect(c); }
    }

    // etykiety: najbliższy wybrany przodek klastra, z którego punkt wypadł
    HdbscanResult res;
    res.label.assign(n, -1);
    res.strength.assign(n, 0.0);
    std::vector<int> cid(C, -1);
    for (int c = 1; c < C; ++c)
        if (selected[c]) cid[c] = static_cast<int>(res.stability.size()), res.stability.push_back(stab[c]);
    std::vector<double> maxlam(res.stability.size(), 0.0);
    for (int p = 0; p < n; ++p) {
        int c = fell_from[p];
        while (c > 0 && !selected[c]) c = parent[c];
        if (c > 0) {
            res.label[p] = cid[c];
            maxlam[cid[c]] = std::max(maxlam[cid[c]], fell_lambda[p]);
        }
    }
    for (int p = 0; p < n; ++p)
        if (res.label[p] >= 0 && maxlam[res.label[p]] > 0)
            res.strength[p] = fell_lambda[p] / maxlam[res.label[p]];
    return res;
}

}  // namespace ftf
