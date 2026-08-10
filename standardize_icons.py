import os
import re

EDIT_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>'

DELETE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>'

def process_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    # We will look for <a ...> ... </a> or <button ...> ... </button> containing title="Editar..." or title="Eliminar..."
    
    def repl_edit_a(m):
        attrs = m.group(1)
        # remove old class and style
        attrs = re.sub(r'\s*class="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*style="[^"]*"', '', attrs)
        return f'<a class="btn-icon-premium"{attrs}>{EDIT_SVG}</a>'

    def repl_edit_btn(m):
        attrs = m.group(1)
        attrs = re.sub(r'\s*class="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*style="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*onmouseover="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*onmouseout="[^"]*"', '', attrs)
        return f'<button class="btn-icon-premium"{attrs}>{EDIT_SVG}</button>'

    def repl_delete_a(m):
        attrs = m.group(1)
        attrs = re.sub(r'\s*class="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*style="[^"]*"', '', attrs)
        return f'<a class="btn-icon-premium danger"{attrs}>{DELETE_SVG}</a>'

    def repl_delete_btn(m):
        attrs = m.group(1)
        attrs = re.sub(r'\s*class="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*style="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*onmouseover="[^"]*"', '', attrs)
        attrs = re.sub(r'\s*onmouseout="[^"]*"', '', attrs)
        return f'<button class="btn-icon-premium danger"{attrs}>{DELETE_SVG}</button>'

    # Replace <a ... title="Editar..."> ... </a>
    content = re.sub(r'<a([^>]*title="Editar[^"]*"[^>]*)>.*?</a>', repl_edit_a, content, flags=re.DOTALL)
    # Replace <button ... title="Editar..."> ... </button>
    content = re.sub(r'<button([^>]*title="Editar[^"]*"[^>]*)>.*?</button>', repl_edit_btn, content, flags=re.DOTALL)

    # Replace <a ... title="Eliminar..."> ... </a>
    content = re.sub(r'<a([^>]*title="Eliminar[^"]*"[^>]*)>.*?</a>', repl_delete_a, content, flags=re.DOTALL)
    # Replace <button ... title="Eliminar..."> ... </button>
    content = re.sub(r'<button([^>]*title="Eliminar[^"]*"[^>]*)>.*?</button>', repl_delete_btn, content, flags=re.DOTALL)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

for root, dirs, files in os.walk("templates"):
    for file in files:
        if file.endswith(".html"):
            process_file(os.path.join(root, file))
print("Done")

