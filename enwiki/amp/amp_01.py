import pywikibot
import re
import os
import requests
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
#import html

# target site
site = pywikibot.Site('en', 'wikipedia')

max_edits = 5
edit_counter = 0

log_file = os.path.join(os.path.expanduser("~"), "enwiki", "amp", "logs", "amp_log.txt")
change_file = os.path.join(os.path.expanduser("~"), "enwiki", "amp", "logs", "amp_change.txt")
list_file = os.path.join(os.path.expanduser("~"), "enwiki", "amp", "logs", "amp_list.txt")
skip_file = os.path.join(os.path.expanduser("~"), "enwiki", "amp", "logs", "amp_skip.txt")

# define AMP keywords to detect AMP links in URLs
AMP_KEYWORDS = ["/amp", "amp/", ".amp", "amp.", "?amp", "amp?", "=amp", 
                "amp=", "&amp", "amp&", "%amp", "amp%", "_amp", "amp_"]

def is_amp_url(url):
    ## check if the URL contains AMP in the subdomain, path, or query
    parsed_url = urlparse(url)

    # check for AMP in the subdomain
    if parsed_url.netloc.startswith('amp.'):
        return True
    
    # check AMP keywords in the path (not in the domain)
    for keyword in AMP_KEYWORDS:
        if keyword in parsed_url.path:
            return True
    
    # check AMP keywords in query parameters
    query_params = dict(parse_qsl(parsed_url.query))
    for param in query_params:
        if 'amp' in param:
            return True

    return False

def clean_amp_url(url):
    ## cleanup AMP artifacts
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    path = parsed_url.path
    query_params = dict(parse_qsl(parsed_url.query))

    # handle subdomain-based AMP (e.g., amp.example.com → www.example.com)
    if domain.startswith('amp.'):
        cleaned_domain = domain.replace('amp.', 'www.', 1)  # Replace 'amp.' with 'www.'
        parsed_url = parsed_url._replace(netloc=cleaned_domain)
        print(f"Subdomain cleaned: {cleaned_domain}")

    # handle path-based AMP (e.g., example.com/amp/article → example.com/article)
    if '/amp/' in path:
        cleaned_path = path.replace('/amp/', '/')
        parsed_url = parsed_url._replace(path=cleaned_path)
        print(f"Path cleaned from /amp/: {cleaned_path}")

    # handle suffix-based AMP (e.g., example.com/article-amp.html → example.com/article.html)
    if path.endswith('-amp.html'):
        cleaned_path = path.replace('-amp.html', '.html')
        parsed_url = parsed_url._replace(path=cleaned_path)
        print(f"Suffix cleaned from -amp.html: {cleaned_path}")
    elif path.endswith('-amp'):
        cleaned_path = path.replace('-amp', '')
        parsed_url = parsed_url._replace(path=cleaned_path)
        print(f"Suffix cleaned from -amp: {cleaned_path}")
    
    # handle specific "Economic Times" AMP pattern (e.g., amp_articleshow → articleshow)
    if 'amp_articleshow' in path:
        cleaned_path = path.replace('amp_articleshow', 'articleshow')
        parsed_url = parsed_url._replace(path=cleaned_path)
        print(f"Specific pattern 'amp_articleshow' cleaned: {cleaned_path}")

    # remove AMP-related query parameters (e.g., amp=1, amp=true)
    cleaned_query = {k: v for k, v in query_params.items() if 'amp' not in k.lower()}
    parsed_url = parsed_url._replace(query=urlencode(cleaned_query))

    # rebuild the cleaned URL
    cleaned_url = urlunparse(parsed_url)
    print(f"Cleaned URL: {cleaned_url}")

    return cleaned_url

def test_url(url):
    ## test if the URL resolves correctly by making a HEAD request
    try:
        response = requests.head(url, allow_redirects=True, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False

def clean_amp_url_with_test(url, title):
    ## clean AMP artifacts from the URL and test if the cleaned URL works
    cleaned_url = clean_amp_url(url)

    # test if the cleaned URL resolves correctly
    if test_url(cleaned_url):
        return cleaned_url
    else:
        # if the cleaned URL doesn't work, log it in the skip file and return the original AMP URL
        with open(skip_file, "a", encoding="utf-8") as f:
            f.write(f"{title}: {url}\n")
        return url

def find_and_replace_amp_links_in_refs(text, title):
    """Find and replace AMP links inside <ref>...</ref> tags."""
    ref_pattern = re.compile(r'<ref[^>]*>(.*?)</ref>', re.DOTALL)
    matches = ref_pattern.findall(text)

    changes_made = False
    updated_text = text

    for ref in matches:
        print(f"Processing reference")

        # detect all URLs within the reference text
        urls_in_ref = re.findall(r'https?://[^\s|<]+', ref)  # regex to handle URLs split by '|'

        for url in urls_in_ref:
            if is_amp_url(url):
                print(f"AMP URL detected: {url}")
                cleaned_url = clean_amp_url(url)  # Clean the AMP URL

                if cleaned_url != url:
                    # Replace the old AMP URL with the cleaned URL
                    updated_ref = ref.replace(url, cleaned_url)
                    updated_text = updated_text.replace(ref, updated_ref)
                    print(f"Replaced AMP URL with Cleaned URL: {cleaned_url}")
                    changes_made = True

                    # log the changes
                    with open(list_file, "a", encoding="utf-8") as f:
                        f.write(f"Article: {title}\nOld AMP URL: {url}\nCleaned URL: {cleaned_url}\n\n")
                else:
                    print(f"No change needed for URL: {url}")

    return updated_text, changes_made

def process_templates(page, text):
    """Process citation templates like {{cite web}}, {{cite news}}, etc., and clean AMP links."""
    changes_made = False
    templates = page.templatesWithParams()

    for template, params in templates:
        template_name = template.title().lower()

        # only handle common citation templates that typically contain URLs
        if template_name.startswith('cite'):
            for i, param in enumerate(params):
                # check for URL-related parameters (e.g., url= or archive-url=)
                if param.startswith('url=') or param.startswith('archive-url='):
                    key, value = param.split('=', 1)
                    url = value.strip()  # extract the actual URL value

                    if is_amp_url(url):
                        cleaned_url = clean_amp_url(url)
                        if cleaned_url != url:
                            # replace only the URL part of the parameter, keeping the key intact (e.g., url=)
                            params[i] = f"{key}={cleaned_url}"
                            changes_made = True

            # rebuild the updated template, and replace it in the text
            updated_template = "{{" + template.title() + "|" + "|".join(params) + "}}"
            text = text.replace(str(template), updated_template)

    return text, changes_made

"""

def find_and_replace_amp_links(text, page):
    text = html.unescape(text)  # Decode any HTML entities
    
    updated_text, ref_changes_made = find_and_replace_amp_links_in_refs(text, page.title())
    updated_text, template_changes_made = process_templates(page, updated_text)
    
    changes_made = ref_changes_made or template_changes_made
    return updated_text, changes_made
"""

def find_and_replace_amp_links(text, page):
    ## find and replace AMP links, including in ref tags, and templates
    
    # clean URLs inside <ref> tags
    updated_text, ref_changes_made = find_and_replace_amp_links_in_refs(text, page.title())
    
    # clean URLs inside templates
    updated_text, template_changes_made = process_templates(page, updated_text)

    # check if any changes were made
    changes_made = ref_changes_made or template_changes_made

    return updated_text, changes_made

def process_page(page, edit_counter):
#def process_page(page):
    ## process page, find AMP links, and update if necessary
    #global edit_counter
    original_text = page.text
    updated_text, changes_made = find_and_replace_amp_links(original_text, page)

    if changes_made:
        print(f"changes made to page: {page.title()}")
    else:
        print(f"no changes made to page: {page.title()}")
    
    # only save changes if any AMP links were cleaned
    if changes_made:
        page.text = updated_text
        #page.save(summary="removed AMP tracking from URLs") 
        edit_counter += 1
        with open(list_file, "a", encoding="utf-8") as f:
            f.write(f"{page.title()}\n")
        with open(change_file, "a", encoding="utf-8") as f:
            f.write(f"* updated text for {page.title()}:\n{updated_text}\n")
            f.write("="*40 + "\n")
        print(f"updated page: {page.title()}")
    else:
        print(f"no changes made to page: {page.title()}")

    return edit_counter

def main():
    global edit_counter

    # path to the file containing article titles (modify this as needed)
    input_file = os.path.join(os.path.expanduser("~"), "enwiki", "amp", "input_file.txt")
    
    # open the file and read article titles line by line
    with open(input_file, 'r', encoding='utf-8') as f:
        # strip leading and trailing whitespace from each line (including the 4 spaces before each title)
        article_titles = [line.strip() for line in f.readlines() if line.strip()]

    # check if the input file contains titles
    if not article_titles:
        print(f"error: no article titles found in {input_file}.")
        return

    # iterate over each article title and process the corresponding page
    for title in article_titles:
        try:
            page = pywikibot.Page(site, title)  # fetch the page by title
            print(f"processing page: {page.title()}")
            edit_counter = process_page(page, edit_counter)  # pass both page and edit_counter
        except Exception as e:
            print(f"error processing page {title}: {e}")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"* failed to process {title}: {e}\n")

    # final summary of changes
    print(f"total pages updated: {edit_counter}")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"* total pages updated: {edit_counter}")

if __name__ == "__main__":
    main()

"""
def main():
    global edit_counter
    # go through each page in the main namespace (Namespace 0)
    for page in site.allpages(namespace=0):
        if edit_counter >= max_edits:
            print(f"Reached the maximum limit of {max_edits} edits. Exiting.")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"Error processing {page.title()}: {e}\n")
            break
        print(f"Processing page: {page.title()}")
        try:
            edit_counter = process_page(page, edit_counter)
        except Exception as e:
            print(f"Error processing page {page.title()}: {e}")
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"* Error processing page {page.title()}: {e}")
    # Final summary of changes
    print(f"Total pages updated: {edit_counter}")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"* Total pages updated: {edit_counter}")
if __name__ == "__main__":
    main()
"""
"""
def main():
    global edit_counter
    # single page
    page_title = "User:KiranBOT/sandbox/amp"
    page = pywikibot.Page(site, page_title)
    print(f"Processing page: {page.title()}")
    try:
        process_page(page)
    except Exception as e:
        print(f"Error processing page {page.title()}: {e}")
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"* Failed to save changes on {page.title()}: {e}\n")
    # Final summary of changes
    print(f"Total pages updated: {edit_counter}")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(f"* script exited.\n")

if __name__ == "__main__":
    main()
"""
