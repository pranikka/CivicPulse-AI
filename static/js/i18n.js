// CivicPulse AI - complete English/Tamil UI translation layer.
// Exact phrases are translated first; a word-level fallback covers dynamic
// labels. User data, IDs, names, codes and technical values are preserved.
(async function () {
    try {
        const response = await fetch('/api/translations', {headers:{'Accept':'application/json'}});
        if (!response.ok) return;
        const data = await response.json();
        if (data.language !== 'ta') return;

        const phrases = data.translations || {};
        const words = data.word_translations || {};
        const phraseKeys = Object.keys(phrases).sort((a,b)=>b.length-a.length);

        function translate(value) {
            if (!value || !/[A-Za-z]/.test(value)) return value;
            // If the node already contains Tamil, only translate remaining English
            // fragments; this prevents accidental mixed-language output.

            const trimmed = value.trim();
            const exact = phrases[trimmed];
            if (exact) return value.replace(trimmed, exact);

            // Preserve URLs, request IDs, email addresses, numbers and values in brackets.
            let result = value;
            phraseKeys.forEach(key => {
                if (!key || key.length < 2) return;
                const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                result = result.replace(new RegExp('(^|[^A-Za-z])' + escaped + '(?=$|[^A-Za-z])', 'gi'), (m,prefix)=>prefix + phrases[key]);
            });

            // Translate common individual UI words only. This intentionally does not
            // translate arbitrary proper names or database values.
            if (Object.keys(words).length) {
                result = result.replace(/\b[A-Za-z][A-Za-z-]*\b/g, token => {
                    const translated = words[token.toLowerCase()];
                    return translated || token;
                });
            }
            return result;
        }

        function translateElement(el) {
            if (el.nodeType !== Node.TEXT_NODE) return;
            const value = el.nodeValue;
            if (!value || !/[A-Za-z]/.test(value)) return;
            // Skip script/style/code/pre content and URLs.
            const parent = el.parentElement;
            if (parent && /^(SCRIPT|STYLE|CODE|PRE)$/i.test(parent.tagName)) return;
            el.nodeValue = translate(value);
        }

        function translateAttributes(root=document) {
            root.querySelectorAll('[placeholder],[title],[aria-label],[data-i18n],[value]').forEach(el => {
                ['placeholder','title','aria-label','data-i18n'].forEach(attr => {
                    const value = el.getAttribute(attr);
                    if (value) el.setAttribute(attr, translate(value));
                });
                // Only translate button-like values; never mutate IDs or arbitrary form data.
                if ((el.tagName === 'INPUT' || el.tagName === 'BUTTON') &&
                    el.getAttribute('type') !== 'hidden' && el.hasAttribute('value')) {
                    const value = el.getAttribute('value');
                    if (value) el.setAttribute('value', translate(value));
                }
            });
            root.querySelectorAll('option').forEach(option => {
                option.textContent = translate(option.textContent);
            });
        }

        function translatePage(root=document.body) {
            if (!root) return;
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
            const nodes = [];
            while (walker.nextNode()) nodes.push(walker.currentNode);
            nodes.forEach(translateElement);
            translateAttributes(root);
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => translatePage());
        } else {
            translatePage();
        }

        // Charts, notifications and other existing dynamic components can insert
        // new DOM nodes after initial load; translate those nodes without rebuilding them.
        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.TEXT_NODE) translateElement(node);
                    else if (node.nodeType === Node.ELEMENT_NODE) translatePage(node);
                });
            });
        });
        observer.observe(document.body, {childList:true, subtree:true});
    } catch (error) {
        console.debug('Translation service unavailable', error);
    }
})();
