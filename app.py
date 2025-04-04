from flask import Flask, render_template, request, jsonify, make_response, session
from googlesearch import search
import requests
from bs4 import BeautifulSoup
import re
import time
import csv
import io
import os
from datetime import timedelta

app = Flask(__name__)

# Production configuration
if os.environ.get('FLASK_ENV') == 'production':
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')  # Change this in production
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
else:
    app.secret_key = os.urandom(24)  # For development only

app.permanent_session_lifetime = timedelta(hours=1)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error='Page not found'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('error.html', error='Internal server error'), 500

def google_search_scraper(keyword, num_results=10):
    try:
        links = []
        count_urls = 1
        unwanted_urls = ['https://www.youtube.com', 'https://en.wikipedia.org/']

        for url in search(keyword, start=0, country='us', lang='en'):
            if count_urls > num_results:
                break
            elif any(unwanted_url in url for unwanted_url in unwanted_urls):
                continue
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    links.append(url)
                    count_urls += 1
            except:
                continue
                
        return links
    except Exception as e:
        print(f"Error in google_search_scraper: {str(e)}")
        return []

def scrap_html(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')

        body = soup.body
        if body is None:
            return {'total_word_count': 0, "total_image_count": 0,
                   "total_heading_count": 0, "total_links_count": 0}

        # Remove script, style, header, footer, and navigation elements
        for element in body(["script", "style", "header", "footer", "nav"]):
            element.decompose()

        # Remove elements with common header/footer/nav classes
        for element in body.find_all(class_=lambda x: x and any(cls in x.lower() for cls in ['header', 'footer', 'nav', 'navigation', 'menu', 'sidebar'])):
            element.decompose()

        # Remove elements with common header/footer/nav IDs
        for element in body.find_all(id=lambda x: x and any(id_name in x.lower() for id_name in ['header', 'footer', 'nav', 'navigation', 'menu', 'sidebar'])):
            element.decompose()

        text = body.get_text(strip=False)
        words = re.findall(r'\w+', text)
        total_word_count = len(words)

        # Only count images in the main content area
        images = body.find_all('img')
        total_image_count = len(images)

        # Only count headings in the main content area
        headings = body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        total_heading_count = len(headings)

        # Only count links in the main content area
        links = body.find_all('a')
        total_links_count = len(links)

        return {
            'total_word_count': total_word_count,
            "total_image_count": total_image_count,
            "total_heading_count": total_heading_count,
            "total_links_count": total_links_count
        }
    except Exception as e:
        print(f"Error in scrap_html for {url}: {str(e)}")
        return {
            'total_word_count': 0,
            "total_image_count": 0,
            "total_heading_count": 0,
            "total_links_count": 0
        }

@app.route('/')
def index():
    # Clear any existing session data
    session.clear()
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search_results():
    try:
        keyword = request.json.get('keyword', '')
        if not keyword:
            return jsonify({'error': 'Please provide a search keyword'}), 400

        # Check if we have cached results for this keyword
        if 'search_results' in session and session['search_results'].get('keyword') == keyword:
            return jsonify(session['search_results']['data'])

        num_results = 10
        results = google_search_scraper(keyword, num_results)
        
        if not results:
            return jsonify({'error': 'No results found'}), 404

        final_result = {
            'total_word_count': 0,
            "total_image_count": 0,
            "total_heading_count": 0,
            "total_links_count": 0
        }
        
        detailed_results = []
        successful_scrapes = 0
        
        for each_link in results:
            count_results = scrap_html(each_link)
            if count_results['total_word_count'] > 0:  # Only count successful scrapes
                final_result['total_word_count'] += count_results['total_word_count']
                final_result['total_image_count'] += count_results['total_image_count']
                final_result['total_heading_count'] += count_results['total_heading_count']
                final_result['total_links_count'] += count_results['total_links_count']
                successful_scrapes += 1
                
                # Add detailed results for this URL
                detailed_results.append({
                    'url': each_link,
                    'word_count': count_results['total_word_count'],
                    'image_count': count_results['total_image_count'],
                    'heading_count': count_results['total_heading_count'],
                    'link_count': count_results['total_links_count']
                })

        if successful_scrapes == 0:
            return jsonify({'error': 'Could not scrape any results'}), 500

        avg_of_final_result = {
            'avg_word_count': final_result['total_word_count'] // successful_scrapes,
            'avg_image_count': final_result['total_image_count'] // successful_scrapes,
            'avg_heading_count': final_result['total_heading_count'] // successful_scrapes,
            'avg_links_count': final_result['total_links_count'] // successful_scrapes,
            'detailed_results': detailed_results
        }

        # Store results in session
        session['search_results'] = {
            'keyword': keyword,
            'data': avg_of_final_result
        }
        session.permanent = True  # Make the session permanent

        return jsonify(avg_of_final_result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/export-csv', methods=['POST'])
def export_csv():
    try:
        # Check if we have cached results
        if 'search_results' not in session:
            return jsonify({'error': 'No data to export'}), 400

        data = session['search_results']['data']['detailed_results']
        if not data:
            return jsonify({'error': 'No data to export'}), 400

        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(['URL', 'Word Count', 'Image Count', 'Heading Count', 'Link Count'])
        
        # Write data
        for row in data:
            writer.writerow([
                row['url'],
                row['word_count'],
                row['image_count'],
                row['heading_count'],
                row['link_count']
            ])
        
        # Create response
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers['Content-Disposition'] = 'attachment; filename=search_results.csv'
        response.headers['Content-type'] = 'text/csv'
        
        return response
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False) 