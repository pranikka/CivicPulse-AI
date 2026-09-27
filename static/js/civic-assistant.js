// CivicPulse AI - existing assistant open/close behavior (preserved)
(function () {
    function initAssistant() {
        const launcher = document.getElementById('civicAssistantLauncher');
        const panel = document.getElementById('civicAssistantPanel');
        const closeButton = document.getElementById('civicAssistantClose');
        const form = document.getElementById('civicAssistantForm');
        const input = document.getElementById('civicAssistantInput');
        const messages = document.getElementById('civicAssistantMessages');
        if (!launcher || !panel || !form || !input || !messages) return;

        function setOpen(open) {
            panel.hidden = !open;
            launcher.setAttribute('aria-expanded', String(open));
            if (open) {
                input.focus();
            } else {
                launcher.focus({preventScroll:true});
            }
        }

        function addMessage(text, type) {
            const div = document.createElement('div');
            div.className = type === 'user' ? 'assistant-user-message' : 'assistant-message';
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        launcher.setAttribute('aria-controls', 'civicAssistantPanel');
        launcher.setAttribute('aria-expanded', String(!panel.hidden));

        launcher.addEventListener('click', (event) => {
            event.preventDefault();
            setOpen(panel.hidden);
        });

        // Explicit, keyboard-accessible close control.
        closeButton?.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            setOpen(false);
        });

        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !panel.hidden) {
                setOpen(false);
            }
        });

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const message = input.value.trim();
            if (!message) return;
            addMessage(message, 'user');
            input.value = '';
            try {
                const response = await fetch('/api/civic-assistant', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message})
                });
                const data = await response.json();
                addMessage(
                    data.success ? data.answer : (data.error || 'Unable to answer right now.'),
                    'assistant'
                );
            } catch (error) {
                addMessage('The assistant is temporarily unavailable. Please use the navigation menu.', 'assistant');
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAssistant);
    } else {
        initAssistant();
    }
})();
