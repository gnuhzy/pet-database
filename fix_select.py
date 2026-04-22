import re

with open('pawtrack_demo.html', 'r') as f:
    content = f.read()

old_css = """	.mode-tabs{display:inline-flex;gap:4px;padding:4px;border:1px solid var(--color-border-secondary);border-radius:var(--border-radius-md);background:var(--color-background-secondary)}
	.mode-tab{font-family:var(--font-sans);font-size:13px;font-weight:700;border:none;border-radius:var(--border-radius-sm);padding:8px 12px;background:transparent;color:var(--color-text-secondary);cursor:pointer}
	.mode-tab.active{background:var(--color-background-primary);color:var(--color-primary);box-shadow:var(--shadow-sm)}
	.assistant-control{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:1rem}
	.assistant-control label{font-size:12px;font-weight:700;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:0.5px}"""

new_css = """	.mode-tabs{display:inline-flex;gap:4px;padding:4px;border:1px solid var(--color-border-secondary);border-radius:var(--border-radius-md);background:var(--color-background-secondary)}
	.mode-tab{font-family:var(--font-sans);font-size:13px;font-weight:700;border:none;border-radius:var(--border-radius-sm);padding:8px 12px;background:transparent;color:var(--color-text-secondary);cursor:pointer;transition:all 0.2s ease;}
	.mode-tab:hover:not(.active){color:var(--color-text-primary)}
	.mode-tab.active{background:var(--color-background-primary);color:var(--color-primary);box-shadow:var(--shadow-sm)}
	.assistant-control{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:1.5rem;background:var(--color-background-primary);padding:16px 20px;border-radius:var(--border-radius-lg);box-shadow:var(--shadow-sm);border:1px solid rgba(255,255,255,0.8);}
	@media (prefers-color-scheme: dark) { .assistant-control{background:rgba(37,38,43,0.6);border-color:rgba(255,255,255,0.05);} }
	.assistant-control label{font-size:12px;font-weight:700;color:var(--color-text-secondary);text-transform:uppercase;letter-spacing:0.5px}
	.assistant-control select{font-family:var(--font-sans);font-size:13px;font-weight:600;padding:8px 32px 8px 12px;border:1px solid var(--color-border-secondary);border-radius:var(--border-radius-md);background:var(--color-background-secondary) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E") no-repeat right 10px center;appearance:none;-webkit-appearance:none;color:var(--color-text-primary);cursor:pointer;transition:all 0.2s;box-shadow:var(--shadow-sm);}
	.assistant-control select:hover{border-color:var(--color-primary);background-color:var(--color-background-primary);}
	.assistant-control select:focus{border-color:var(--color-primary);box-shadow:0 0 0 3px var(--color-primary-light);outline:none;}"""

content = content.replace(old_css, new_css)

with open('pawtrack_demo.html', 'w') as f:
    f.write(content)

with open('test.html', 'w') as f:
    f.write(content)

