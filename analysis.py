from crawl import Crawler
from notifier.notifier import Notifier
import tldextract
import dbMysql
import dbClass
import env
import time


class Analyser:
    def __init__(self):
        self.crawler = Crawler()
        self.mysql_obj = dbMysql.DbMysql(env.DB_HOST, env.DB_PORT, env.DB_USERNAME, env.DB_PASSWORD, env.DB_DATABASE)
        self.db_obj = dbClass.DbWrapper(self.mysql_obj)

    def auth(self, api_key):
        # User-check with given API key.
        id_check = self.db_obj.get_data("api_key",
                                        COLUMNS="*",
                                        WHERE=[{'init': {'api_key': api_key}}],
                                        OPERATOR="eq")
        # Check if API key is valid.
        if id_check:
            user_id = id_check[0]['user_id']
            user_check = self.db_obj.get_data("user",
                                              COLUMNS=["id", "name_surname", "email"],
                                              WHERE=[{'init': {'id': user_id}}],
                                              OPERATOR="eq")
            # Check which user's key it is.
            if user_check:
                user_data = user_check[0]
                return {'user_id': user_id, 'name': user_data['name_surname'], 'email': user_data['email']}
            else:
                return False
        else:
            return False

    def find_errors(self, defined_errors, crawl_data, url_id):
        url_error_list = []
        url_meta_list = []
        # Scan the metadata according to defined errors.
        for error in defined_errors:
            url_meta_content = None
            if error['attribute']:  # Compound metadata
                found_tag = crawl_data.find(error['tag'], attrs={error['attribute']: error['value']})

                # Are we checking for missing attribs?
                missing_mode = True if error['content'] is None else False

                if found_tag:
                    if found_tag['content']:
                        found_tag_content = found_tag['content']
                        if found_tag_content != "":  # Yeah it exists, but is it an empty string?
                            url_meta_content = found_tag_content
                            # Now we can check if we're analysing duplicates.
                            if not missing_mode:
                                # Check for duplicates.
                                dup_check = self.db_obj.exists('analysed_url_meta',
                                                               [('tag', error['tag']),
                                                                ('attribute', error['attribute']),
                                                                ('value', error['value']),
                                                                ('content', found_tag_content)],
                                                               exclude=('url_id', url_id))
                                if dup_check is not False:
                                    url_error_list.append(True)  # Duplicate!
                                else:
                                    url_error_list.append(False)  # Not duplicate!
                            else:
                                # Check for missing. But it is already non-empty.
                                url_error_list.append(False)
                        else:
                            # Tag content is empty.
                            if missing_mode:
                                # Check for missing. It is indeed empty.
                                url_error_list.append(True)
                            else:
                                # It is missing but we are checking for duplicates right now.
                                url_error_list.append(False)
                    else:
                        if missing_mode:
                            # The tag is missing. Put it in the errors.
                            url_error_list.append(True)
                        else:
                            # It is missing but we are checking for duplicates right now.
                            url_error_list.append(False)
                else:
                    # Tag is missing.
                    if missing_mode:
                        # The tag is missing. Put it in the errors.
                        url_error_list.append(True)
                    else:
                        # It is missing but we are checking for duplicates right now.
                        url_error_list.append(False)
            else:  # Simple tag checking
                found_tag = crawl_data.find(error['tag'])

                # Are we checking for missing attribs?
                missing_mode = True if error['content'] is None else False

                if found_tag:  # No need for checking duplication if it's already missing.
                    if found_tag.text:
                        found_tag_content = found_tag.text
                        url_meta_content = found_tag_content
                        # Now we can check if we're analysing duplicates.
                        if not missing_mode:
                            # Check for duplicates.
                            dup_check = self.db_obj.exists('analysed_url_meta', [('tag', error['tag']),
                                                                                 ('attribute', error['attribute']),
                                                                                 ('value', error['value']),
                                                                                 ('content', found_tag_content)],
                                                           exclude=('url_id', url_id))
                            # Warn if the error did not exist before or notify if the error is fixed this time.
                            if dup_check is not False:
                                # Duplicate!
                                url_error_list.append(True)
                            else:
                                # Not duplicate!
                                url_error_list.append(False)
                        else:
                            url_error_list.append(False)
                    else:
                        # Empty tag body?
                        if missing_mode:
                            # Check for missing. It is indeed empty.
                            url_error_list.append(True)
                        else:
                            # It is missing but we are checking for duplicates right now.
                            url_error_list.append(False)
                else:
                    # Tag is missing.
                    if missing_mode:
                        # The tag is missing. Put it in the errors.
                        url_error_list.append(True)
                    else:
                        # It is missing but we are checking for duplicates right now.
                        url_error_list.append(False)
            # Get the single metadata
            if error['content'] is not None:  # TODO: This shit needs to be addressed. There must be a better solution.
                url_meta_list.append({'tag': error['tag'],
                                      'attribute': error['attribute'],
                                      'value': error['value'],
                                      'content': url_meta_content})

        result = list(zip(list(x['id'] for x in defined_errors), url_error_list))
        return result, url_meta_list

    def analyse(self, url, user_data):
        if user_data is not False:
            user_id = user_data['user_id']
            user_name = user_data['name']
        else:
            return None, "Unauthorised!"

        # Proceed for website crawling.
        website_data = self.crawler.get_crawled(url)
        if website_data['status_code'] != 200:
            return None, "Non-OK HTTP response received!"

        # Handle the URL changes for 301, 302, etc.
        url = website_data['url']

        # Obtain crawl data for website.
        crawl = website_data['content']

        # Add to analysed_url table of our database with the correct timestamp.
        checked_id = self.db_obj.exists('analysed_url', [('url', url)])
        if checked_id:  # It exists. Update the time accessed to it.
            url_id = checked_id

            # Update the time of this url.
            try:
                self.db_obj.update_data('analysed_url',
                                        [('time_accessed', time.time())],
                                        checked_id)
            except Exception as e:
                print(e)
                return None, "Action could not be performed. Query did not execute successfully."

            # Get ALL defined SEO Errors. (So that you can check it during analysis.)
            defined_errors = self.db_obj.execute("SELECT * FROM seo_errors")

            # Get the found error list of this URL.
            errors = self.find_errors(defined_errors, crawl, url_id)
            error_list = errors[0]
            meta_list = errors[1]

            # Get the previously existing problems related to that url id.
            previous_url_errors = [row['error_id'] for row in
                                   self.db_obj.execute(
                                       "SELECT error_id FROM analysis_errors WHERE url_id = " + str(checked_id))]

            # Clear out the existing metadata. (I'm not content with this solution. I should've left the unchanged data)
            self.db_obj.execute("DELETE FROM analysed_url_meta WHERE url_id = " + str(url_id))

            # Add the meta data to DB.
            for meta in meta_list:
                self.db_obj.insert_data('analysed_url_meta',
                                        [(url_id, meta['tag'], meta['attribute'], meta['value'], meta['content'])],
                                        COLUMNS=['url_id', 'tag', 'attribute', 'value', 'content'])

            # Iterate the error list
            for error in error_list:
                if error[0] in previous_url_errors and error[1] is False:
                    # Delete the fixed errors.
                    print("Error with id ", error[0], " is fixed now!")
                    self.db_obj.execute(
                        "DELETE FROM analysis_errors "
                        "WHERE url_id = {0} AND error_id = {1} LIMIT 1".format(checked_id, error[0]))
                elif error[0] not in previous_url_errors and error[1] is True:
                    # Add the previously non-existing errors.
                    print("A wild error with id ", error[0], " has just appeared!")  # Pokemon?
                    self.db_obj.insert_data('analysis_errors',
                                            [(url_id, error[0])],
                                            COLUMNS=['url_id', 'error_id'])

        else:  # A unique record.
            try:
                # Find the sub-domain and domain of URL.
                extracted_url = tldextract.extract(url)
                subdomain = extracted_url.subdomain
                domain = extracted_url.domain

                # Add the new site to analysed_url.
                self.db_obj.insert_data('analysed_url',
                                        [(url, subdomain, domain, time.time())],
                                        COLUMNS=['url', 'subdomain', 'domain', 'time_accessed'])
                insert_id = self.db_obj.get_last_insert_id()
                url_id = insert_id

                # Get ALL defined SEO Errors. (So that you can check it during analysis.)
                defined_errors = self.db_obj.execute("SELECT * FROM seo_errors")

                # Get the found error list of this URL.
                errors = self.find_errors(defined_errors, crawl, url_id)
                error_list = errors[0]
                meta_list = errors[1]

                # Add the meta data to DB.
                for meta in meta_list:
                    self.db_obj.insert_data('analysed_url_meta',
                                            [(url_id, meta['tag'], meta['attribute'], meta['value'], meta['content'])],
                                            COLUMNS=['url_id', 'tag', 'attribute', 'value', 'content'])

                # Iterate the error list
                for error in error_list:
                    if error[1] is True:
                        # Add the newly found error.
                        print("A wild error with id ", error[0], " has just appeared!")  # Pokemon?
                        self.db_obj.insert_data('analysis_errors',
                                                [(url_id, error[0])],
                                                COLUMNS=['url_id', 'error_id'])

            except Exception as e:
                print(e)
                return None, "Action could not be performed. Query did not execute successfully."

        # User's analysis was successful.
        try:
            self.db_obj.insert_data('analysis_user',
                                    [(url_id, user_id, time.time())],
                                    COLUMNS=['url_id', 'user_id', 'time'])
            print("Analysis request made by user #{0} ({1}) is successful!".format(user_id, user_name))

            try:
                # Get the issues for the last time.
                sql = """SELECT seo_errors.name, seo_errors.description
                FROM analysis_errors 
                JOIN analysed_url ON analysis_errors.url_id = analysed_url.id 
                JOIN seo_errors ON analysis_errors.error_id = seo_errors.id 
                WHERE analysed_url.id = {0}""".format(url_id)

                issues = self.db_obj.execute(sql)
                error_array = []
                for issue in issues:
                    error_array.append([issue['name'], issue['description']])

                # Fucking successful!
                return {url: error_array}, "Success!"

            except Exception as e:
                print(e)
                return None, "Issues could not be obtained."
        except Exception as e:
            print(e)
            return None, "Action could not be performed. Query did not execute successfully."

    def request_analysis(self, url, api_key, mode):
        auth = self.auth(api_key)
        if auth is False:
            return None, "Invalid API key."

        # Proceed as usual.
        user_data = auth
        user_name = auth['name']
        user_email = auth['email']

        # Obtained results from website(s) will be here.
        urls_error_list = []

        # Check the request mode.
        if mode != "batch":
            if isinstance(url, str):
                urls_error_list.append(self.analyse(url, user_data)[0])
            else:
                return None, "Provided URL is not a string."
        else:
            # for API!
            for link in url:
                urls_error_list.append(self.analyse(link, user_data)[0])

        try:
            # Notify the user about errors & fixes via email.
            notifier = Notifier()
            result = notifier.notify(user_email, user_name, urls_error_list)
        except Exception as e:
            print(e)
            return None, "Email could not be sent!"
        # End of the road.
        return result, "Success!"

    def main(self):
        print(self.request_analysis(["http://127.0.0.1:5000/test-analysis"],
                                    "7882e9e22bfa7dc96a6e8333a66091c51d5fe012",
                                    "batch"))


if __name__ == '__main__':
    a = Analyser()
    a.main()
