from flask import Flask, request, jsonify, render_template_string
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import base64
import json
import os
import time
from datetime import datetime
import requests
from PIL import Image
import io
import colorsys
from openai import OpenAI
from dotenv import load_dotenv
import os
app = Flask(__name__)


# Load environment variables from a .env file
load_dotenv()
# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
class AccessibilityTester:
    def __init__(self):
        self.driver = None
        self.issues = []
        self.screenshots = []
        
    def setup_driver(self):
        """Setup Chrome driver with accessibility-focused options"""
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--force-device-scale-factor=1')
        
        self.driver = webdriver.Chrome(options=options)
        self.driver.implicitly_wait(10)
    
    def capture_screenshot(self, name="screenshot"):
        """Capture screenshot and return base64 encoded image"""
        screenshot = self.driver.get_screenshot_as_png()
        screenshot_b64 = base64.b64encode(screenshot).decode('utf-8')
        
        self.screenshots.append({
            'name': name,
            'data': screenshot_b64,
            'timestamp': datetime.now().isoformat()
        })
        
        return screenshot_b64
    
    def check_color_contrast(self):
        """Check color contrast ratios"""
        issues = []
        
        # Get all text elements
        text_elements = self.driver.find_elements(By.XPATH, "//*[text()]")
        
        for element in text_elements[:50]:  # Limit to avoid timeout
            try:
                # Get computed styles
                text_color = self.driver.execute_script(
                    "return window.getComputedStyle(arguments[0]).color;", element
                )
                bg_color = self.driver.execute_script(
                    "return window.getComputedStyle(arguments[0]).backgroundColor;", element
                )
                font_size = self.driver.execute_script(
                    "return window.getComputedStyle(arguments[0]).fontSize;", element
                )
                
                # Check if element is visible
                if element.is_displayed() and element.text.strip():
                    contrast_ratio = self.calculate_contrast_ratio(text_color, bg_color)
                    
                    if contrast_ratio < 4.5:  # WCAG AA standard
                        issues.append({
                            'type': 'Low Color Contrast',
                            'element': element.tag_name,
                            'text': element.text[:50],
                            'text_color': text_color,
                            'bg_color': bg_color,
                            'contrast_ratio': contrast_ratio,
                            'font_size': font_size,
                            'severity': 'high' if contrast_ratio < 3 else 'medium'
                        })
                        
            except Exception as e:
                continue
                
        return issues
    
    def calculate_contrast_ratio(self, color1, color2):
        """Calculate contrast ratio between two colors"""
        try:
            # Parse RGB values
            def parse_rgb(color_str):
                if color_str.startswith('rgb('):
                    return [int(x) for x in color_str[4:-1].split(',')]
                elif color_str.startswith('rgba('):
                    return [int(x) for x in color_str[5:-1].split(',')[:3]]
                return [0, 0, 0]  # Default to black
            
            def relative_luminance(rgb):
                r, g, b = [x/255.0 for x in rgb]
                def gamma_correct(c):
                    return c/12.92 if c <= 0.03928 else ((c+0.055)/1.055)**2.4
                return 0.2126 * gamma_correct(r) + 0.7152 * gamma_correct(g) + 0.0722 * gamma_correct(b)
            
            rgb1 = parse_rgb(color1)
            rgb2 = parse_rgb(color2)
            
            l1 = relative_luminance(rgb1)
            l2 = relative_luminance(rgb2)
            
            lighter = max(l1, l2)
            darker = min(l1, l2)
            
            return (lighter + 0.05) / (darker + 0.05)
            
        except:
            return 1.0  # Default to failing ratio
    
    def check_alt_text(self):
        """Check for missing or inadequate alt text"""
        issues = []
        
        # Check images
        images = self.driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            try:
                alt_text = img.get_attribute("alt")
                src = img.get_attribute("src")
                
                if not alt_text:
                    issues.append({
                        'type': 'Missing Alt Text',
                        'element': 'img',
                        'src': src,
                        'severity': 'high'
                    })
                elif len(alt_text.strip()) < 3:
                    issues.append({
                        'type': 'Inadequate Alt Text',
                        'element': 'img',
                        'src': src,
                        'alt_text': alt_text,
                        'severity': 'medium'
                    })
                    
            except Exception as e:
                continue
                
        return issues
    
    def check_headings_structure(self):
        """Check heading hierarchy and structure"""
        issues = []
        
        headings = self.driver.find_elements(By.XPATH, "//h1 | //h2 | //h3 | //h4 | //h5 | //h6")
        
        if not headings:
            issues.append({
                'type': 'No Headings Found',
                'severity': 'medium',
                'description': 'Page has no heading elements'
            })
            return issues
        
        # Check for H1
        h1_elements = self.driver.find_elements(By.TAG_NAME, "h1")
        if len(h1_elements) == 0:
            issues.append({
                'type': 'Missing H1',
                'severity': 'high',
                'description': 'Page should have exactly one H1 element'
            })
        elif len(h1_elements) > 1:
            issues.append({
                'type': 'Multiple H1',
                'severity': 'medium',
                'description': f'Page has {len(h1_elements)} H1 elements, should have only one'
            })
        
        # Check heading hierarchy
        previous_level = 0
        for heading in headings:
            level = int(heading.tag_name[1])
            if level > previous_level + 1:
                issues.append({
                    'type': 'Heading Hierarchy Skip',
                    'element': heading.tag_name,
                    'text': heading.text[:50],
                    'severity': 'medium',
                    'description': f'Heading level jumps from H{previous_level} to H{level}'
                })
            previous_level = level
            
        return issues
    
    def check_form_labels(self):
        """Check form inputs for proper labels"""
        issues = []
        
        # Get form elements separately to avoid XPath issues
        form_elements = []
        form_elements.extend(self.driver.find_elements(By.TAG_NAME, "input"))
        form_elements.extend(self.driver.find_elements(By.TAG_NAME, "textarea"))
        form_elements.extend(self.driver.find_elements(By.TAG_NAME, "select"))
        
        for element in form_elements:
            try:
                element_type = element.get_attribute("type")
                if element_type in ['hidden', 'submit', 'button']:
                    continue
                
                # Check for label
                element_id = element.get_attribute("id")
                aria_label = element.get_attribute("aria-label")
                aria_labelledby = element.get_attribute("aria-labelledby")
                
                has_label = False
                
                if element_id:
                    labels = self.driver.find_elements(By.XPATH, f"//label[@for='{element_id}']")
                    if labels:
                        has_label = True
                
                if aria_label or aria_labelledby:
                    has_label = True
                
                if not has_label:
                    issues.append({
                        'type': 'Form Field Missing Label',
                        'element': element.tag_name,
                        'element_type': element_type,
                        'severity': 'high'
                    })
                    
            except Exception as e:
                continue
                
        return issues
    
    def check_keyboard_navigation(self):
        """Check for keyboard navigation issues"""
        issues = []
        
        # Check for focusable elements without visible focus
        focusable_elements = []
        
        # Get all focusable elements separately
        focusable_elements.extend(self.driver.find_elements(By.TAG_NAME, "a"))
        focusable_elements.extend(self.driver.find_elements(By.TAG_NAME, "button"))
        focusable_elements.extend(self.driver.find_elements(By.TAG_NAME, "input"))
        focusable_elements.extend(self.driver.find_elements(By.TAG_NAME, "textarea"))
        focusable_elements.extend(self.driver.find_elements(By.TAG_NAME, "select"))
        focusable_elements.extend(self.driver.find_elements(By.XPATH, "//*[@tabindex]"))
        
        focus_issues = 0
        for element in focusable_elements[:20]:  # Limit to avoid timeout
            try:
                if element.is_displayed() and element.is_enabled():
                    # Focus the element
                    self.driver.execute_script("arguments[0].focus();", element)
                    
                    # Check if focus is visible
                    outline = self.driver.execute_script(
                        "return window.getComputedStyle(arguments[0]).outline;", element
                    )
                    box_shadow = self.driver.execute_script(
                        "return window.getComputedStyle(arguments[0]).boxShadow;", element
                    )
                    
                    if outline == 'none' and 'none' in box_shadow:
                        focus_issues += 1
                        
            except Exception as e:
                continue
        
        if focus_issues > 0:
            issues.append({
                'type': 'Focus Visibility Issues',
                'count': focus_issues,
                'severity': 'high',
                'description': f'{focus_issues} elements lack visible focus indicators'
            })
        
        return issues
    
    def check_semantic_markup(self):
        """Check for semantic HTML usage"""
        issues = []
        
        # Check for landmark elements
        landmarks = ['main', 'nav', 'header', 'footer', 'aside', 'section']
        found_landmarks = []
        
        for landmark in landmarks:
            elements = self.driver.find_elements(By.TAG_NAME, landmark)
            if elements:
                found_landmarks.append(landmark)
        
        if len(found_landmarks) < 3:
            issues.append({
                'type': 'Limited Semantic Markup',
                'found_landmarks': found_landmarks,
                'severity': 'medium',
                'description': 'Page uses limited semantic HTML5 elements'
            })
        
        # Check for lists used for navigation
        nav_elements = self.driver.find_elements(By.TAG_NAME, "nav")
        if nav_elements:
            nav_lists = []
            for nav in nav_elements:
                try:
                    nav_lists.extend(nav.find_elements(By.TAG_NAME, "ul"))
                    nav_lists.extend(nav.find_elements(By.TAG_NAME, "ol"))
                except:
                    continue
            
            if not nav_lists:
                issues.append({
                    'type': 'Navigation Not Using Lists',
                    'severity': 'low',
                    'description': 'Navigation elements should use list markup'
                })
        
        return issues
    
    def check_aria_attributes(self):
        """Check ARIA attributes usage"""
        issues = []
        
        # Check for elements with aria-label but no role
        aria_labeled = self.driver.find_elements(By.XPATH, "//*[@aria-label]")
        
        for element in aria_labeled:
            try:
                role = element.get_attribute("role")
                tag_name = element.tag_name.lower()
                
                if not role and tag_name in ['div', 'span']:
                    issues.append({
                        'type': 'ARIA Label Without Role',
                        'element': tag_name,
                        'aria_label': element.get_attribute("aria-label"),
                        'severity': 'medium'
                    })
                    
            except Exception as e:
                continue
        
        return issues
    
    def check_page_structure(self):
        """Check overall page structure"""
        issues = []
        
        # Check for skip links
        all_links = self.driver.find_elements(By.TAG_NAME, "a")
        skip_links = [link for link in all_links if link.get_attribute("href") and '#' in link.get_attribute("href")]
        has_skip_link = any('skip' in link.text.lower() for link in skip_links if link.text)
        
        if not has_skip_link:
            issues.append({
                'type': 'Missing Skip Link',
                'severity': 'medium',
                'description': 'Page should have a skip to main content link'
            })
        
        # Check page title
        title = self.driver.title
        if not title or len(title.strip()) < 3:
            issues.append({
                'type': 'Missing or Inadequate Page Title',
                'current_title': title,
                'severity': 'high'
            })
        
        # Check for language attribute
        try:
            html_lang = self.driver.find_element(By.TAG_NAME, "html").get_attribute("lang")
            if not html_lang:
                issues.append({
                    'type': 'Missing Language Attribute',
                    'severity': 'medium',
                    'description': 'HTML element should have lang attribute'
                })
        except:
            issues.append({
                'type': 'Missing Language Attribute',
                'severity': 'medium',
                'description': 'HTML element should have lang attribute'
            })
        
        return issues
    
    def generate_ai_summary(self, all_issues, url):
        """Generate AI summary of accessibility issues"""
        try:
            issues_text = json.dumps(all_issues, indent=2)
            
            prompt = f"""
            Analyze the following accessibility issues found on the webpage: {url}
            
            Issues found:
            {issues_text}
            
            Please provide:
            1. A brief executive summary of the accessibility status
            2. Top 3 priority issues that should be fixed first
            3. Specific recommendations for each major issue category
            4. Impact on different user groups (vision, motor, cognitive disabilities)
            5. Estimated effort level (Low/Medium/High) for fixes
            
            Format the response as a structured report.
            """
            
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an accessibility expert providing detailed analysis and recommendations for web accessibility issues."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"Error generating AI summary: {str(e)}"
    
    def run_full_test(self, url):
        """Run comprehensive accessibility test"""
        try:
            self.setup_driver()
            self.driver.get(url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Capture initial screenshot
            self.capture_screenshot("initial_page")
            
            # Run all tests
            all_issues = []
            
            print("Checking color contrast...")
            all_issues.extend(self.check_color_contrast())
            
            print("Checking alt text...")
            all_issues.extend(self.check_alt_text())
            
            print("Checking headings structure...")
            all_issues.extend(self.check_headings_structure())
            
            print("Checking form labels...")
            all_issues.extend(self.check_form_labels())
            
            print("Checking keyboard navigation...")
            all_issues.extend(self.check_keyboard_navigation())
            
            print("Checking semantic markup...")
            all_issues.extend(self.check_semantic_markup())
            
            print("Checking ARIA attributes...")
            all_issues.extend(self.check_aria_attributes())
            
            print("Checking page structure...")
            all_issues.extend(self.check_page_structure())
            
            # Generate AI summary
            print("Generating AI summary...")
            ai_summary = self.generate_ai_summary(all_issues, url)
            
            # Organize results
            results = {
                'url': url,
                'timestamp': datetime.now().isoformat(),
                'total_issues': len(all_issues),
                'issues_by_severity': {
                    'high': len([i for i in all_issues if i.get('severity') == 'high']),
                    'medium': len([i for i in all_issues if i.get('severity') == 'medium']),
                    'low': len([i for i in all_issues if i.get('severity') == 'low'])
                },
                'issues': all_issues,
                'screenshots': self.screenshots,
                'ai_summary': ai_summary
            }
            
            return results
            
        except Exception as e:
            return {'error': str(e)}
            
        finally:
            if self.driver:
                self.driver.quit()

# Flask routes
@app.route('/')
def index():
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Accessibility Testing Tool</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 800px; margin: 0 auto; }
            .form-group { margin: 20px 0; }
            input[type="url"] { width: 100%; padding: 10px; font-size: 16px; }
            button { background: #007cba; color: white; padding: 12px 24px; font-size: 16px; border: none; cursor: pointer; }
            button:hover { background: #005a87; }
            .results { margin-top: 30px; }
            .issue { background: #f5f5f5; padding: 15px; margin: 10px 0; border-left: 4px solid #ccc; }
            .high { border-left-color: #d32f2f; }
            .medium { border-left-color: #f57c00; }
            .low { border-left-color: #388e3c; }
            .loading { text-align: center; margin: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Web Accessibility Testing Tool</h1>
            <p>Enter a URL to perform comprehensive accessibility testing including color contrast, alt text, form labels, keyboard navigation, and more.</p>
            
            <form id="testForm">
                <div class="form-group">
                    <label for="url">Website URL:</label>
                    <input type="url" id="url" name="url" required placeholder="https://example.com">
                </div>
                <button type="submit">Run Accessibility Test</button>
            </form>
            
            <div id="loading" class="loading" style="display: none;">
                <p>Testing in progress... This may take a few minutes.</p>
            </div>
            
            <div id="results" class="results"></div>
        </div>
        
        <script>
            document.getElementById('testForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const url = document.getElementById('url').value;
                const loading = document.getElementById('loading');
                const results = document.getElementById('results');
                
                loading.style.display = 'block';
                results.innerHTML = '';
                
                try {
                    const response = await fetch('/test', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ url: url })
                    });
                    
                    const data = await response.json();
                    loading.style.display = 'none';
                    
                    if (data.error) {
                        results.innerHTML = `<div class="issue high">Error: ${data.error}</div>`;
                    } else {
                        displayResults(data);
                    }
                    
                } catch (error) {
                    loading.style.display = 'none';
                    results.innerHTML = `<div class="issue high">Error: ${error.message}</div>`;
                }
            });
            
            function displayResults(data) {
                const results = document.getElementById('results');
                
                let html = `
                    <h2>Accessibility Test Results</h2>
                    <p><strong>URL:</strong> ${data.url}</p>
                    <p><strong>Total Issues:</strong> ${data.total_issues}</p>
                    <p><strong>Issues by Severity:</strong> 
                        High: ${data.issues_by_severity.high}, 
                        Medium: ${data.issues_by_severity.medium}, 
                        Low: ${data.issues_by_severity.low}
                    </p>
                    
                    <h3>AI Summary</h3>
                    <div class="issue">
                        <pre>${data.ai_summary}</pre>
                    </div>
                    
                    <h3>Detailed Issues</h3>
                `;
                
                data.issues.forEach(issue => {
                    html += `
                        <div class="issue ${issue.severity || 'medium'}">
                            <h4>${issue.type}</h4>
                            <p><strong>Severity:</strong> ${issue.severity || 'medium'}</p>
                            ${issue.description ? `<p><strong>Description:</strong> ${issue.description}</p>` : ''}
                            ${issue.element ? `<p><strong>Element:</strong> ${issue.element}</p>` : ''}
                            ${issue.text ? `<p><strong>Text:</strong> ${issue.text}</p>` : ''}
                            ${issue.contrast_ratio ? `<p><strong>Contrast Ratio:</strong> ${issue.contrast_ratio.toFixed(2)}</p>` : ''}
                        </div>
                    `;
                });
                
                if (data.screenshots && data.screenshots.length > 0) {
                    html += `
                        <h3>Screenshots</h3>
                        <img src="data:image/png;base64,${data.screenshots[0].data}" style="max-width: 100%; border: 1px solid #ccc;">
                    `;
                }
                
                results.innerHTML = html;
            }
        </script>
    </body>
    </html>
    """)

@app.route('/test', methods=['POST'])
def test_accessibility():
    try:
        data = request.get_json()
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        tester = AccessibilityTester()
        results = tester.run_full_test(url)
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Make sure to set your OpenAI API key
    if not os.getenv('OPENAI_API_KEY'):
        print("Warning: OPENAI_API_KEY environment variable not set")
    
    app.run(debug=True, host='0.0.0.0', port=5000)