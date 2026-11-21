({local, inline}) => {
    const inert = document.implementation.createHTMLDocument("");
    const dom = inert.importNode(document.documentElement, true);
    const base = document.baseURI;
    function reference(raw, asset) {
        if (!raw) return raw;
        try {
            const url = new URL(raw, base);
            if (raw.startsWith("#") && url.href.split("#")[0] === document.URL.split("#")[0]) return raw;
            if (!["http:", "https:"].includes(url.protocol)) return raw;
            const fragment = url.hash;
            url.hash = "";
            return asset && Object.hasOwn(local, url.href)
                ? "./page_files/" + local[url.href] + fragment : url.href + fragment;
        } catch { return raw; }
    }
    // HTML srcset URLs can contain commas (including inline data URLs).
    function srcset(value) {
        const candidates = [];
        let i = 0;
        while (i < value.length) {
            while (i < value.length && /[\t\n\f\r ,]/.test(value[i])) i++;
            let start = i;
            while (i < value.length && !/[\t\n\f\r ]/.test(value[i])) i++;
            let url = value.slice(start, i);
            if (!url) break;
            let descriptor = "";
            if (url.endsWith(",")) url = url.replace(/,+$/, "");
            else {
                start = i;
                let depth = 0;
                while (i < value.length && (value[i] !== "," || depth)) {
                    if (value[i] === "(") depth++;
                    if (value[i] === ")" && depth) depth--;
                    i++;
                }
                descriptor = value.slice(start, i).trim();
            }
            candidates.push([reference(url, true), descriptor].filter(Boolean).join(" "));
        }
        return candidates.join(", ");
    }
    for (const n of [dom, ...dom.querySelectorAll("*")]) {
        const tag = n.localName;
        if (tag === "base") n.removeAttribute("href");
        for (const attr of ["src", "poster", "background", "data", "href", "xlink:href", "action", "formaction"]) {
            if (!n.hasAttribute(attr) || (attr === "data" && tag !== "object")) continue;
            const raw = n.getAttribute(attr);
            const asset = ["src", "poster", "background", "data"].includes(attr)
                || (tag === "link" && /(?:^|\s)(?:stylesheet|icon|preload|modulepreload|prefetch|manifest)(?:$|\s)/i.test(n.rel))
                || ["image","use"].includes(tag);
            n.setAttribute(attr, reference(raw, asset));
            if (n.matches("link[rel~=stylesheet]") && n.getAttribute(attr).startsWith("./page_files/")) {
                n.removeAttribute("integrity"); // The saved CSS has rewritten URLs.
            }
        }
        if (tag === "form" && !n.getAttribute("action")) n.setAttribute("action", document.URL);
        for (const attr of ["srcset", "imagesrcset"]) {
            if (n.hasAttribute(attr)) n.setAttribute(attr, srcset(n.getAttribute(attr)));
        }
        if (n.hasAttribute("style") && Object.hasOwn(inline, n.getAttribute("style"))) {
            n.setAttribute("style", inline[n.getAttribute("style")]);
        }
        if (tag === "style" && Object.hasOwn(inline, n.textContent)) n.textContent = inline[n.textContent];
        if (tag === "meta" && n.hasAttribute("charset")) n.setAttribute("charset", "utf-8");
        if (tag === "meta" && n.httpEquiv.toLowerCase() === "content-type") n.content = "text/html; charset=utf-8";
    }
    const charset = inert.createElement("meta");
    charset.setAttribute("charset", "utf-8");
    dom.querySelector("head")?.prepend(charset);
    const doctype = document.doctype ? new XMLSerializer().serializeToString(document.doctype) + "\n" : "";
    return doctype + dom.outerHTML;
}
