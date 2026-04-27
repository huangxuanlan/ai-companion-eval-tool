import os
import re

def main():
    html_path = 'index.html'
    with open(html_path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Create directories
    os.makedirs('css', exist_ok=True)
    os.makedirs('js', exist_ok=True)

    # 1. Extract CSS
    style_pattern = re.compile(r'<style>(.*?)</style>', re.DOTALL)
    style_match = style_pattern.search(html)
    if style_match:
        css_content = style_match.group(1).strip()
        with open('css/main.css', 'w', encoding='utf-8') as f:
            f.write(css_content)
        # Replace inline style with link
        html = html[:style_match.start()] + '  <link rel="stylesheet" href="css/main.css">\n' + html[style_match.end():]

    # 2. Extract Javascript
    script_pattern = re.compile(r'<script>\s*(.*?)\s*</script>', re.DOTALL)
    script_matches = list(script_pattern.finditer(html))
    
    if script_matches:
        all_js = []
        for match in script_matches:
            all_js.append(match.group(1).strip())
            
        with open('js/legacy_bundle.js', 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(all_js))
            
        # Remove original inline scripts smoothly, reversing to not mess up indices
        for match in reversed(script_matches):
            html = html[:match.start()] + html[match.end():]
        
        # Clean up empty comments like <!-- JS Part B -->
        html = re.sub(r'<!--\s*JS Part [A-Z]\s*-->\s*', '', html)

        # Inject new script tag before </body>
        body_end = html.rfind('</body>')
        if body_end != -1:
            html = html[:body_end] + '  <script src="js/legacy_bundle.js"></script>\n' + html[body_end:]

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
        
    print("Extraction successful! Created css/main.css and js/legacy_bundle.js.")

if __name__ == '__main__':
    main()
