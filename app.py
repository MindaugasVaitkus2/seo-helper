from flask import Flask, request, Response, jsonify, make_response, render_template, redirect, url_for
from analysis import Analyser
import xml.etree.ElementTree as ET
import tldextract
import bcrypt
import traceback
import time
import dbMysql
import dbClass
import env
import secrets

app = Flask(__name__)

# TODO: You MUST remove these when not in dev environment.
app.config['ENV'] = 'development'
app.config['TESTING'] = True
app.config['DEBUG'] = True
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['TRAP_BAD_REQUEST_ERRORS'] = True

mysql_obj = dbMysql.DbMysql(env.DB_HOST, env.DB_PORT, env.DB_USERNAME, env.DB_PASSWORD, env.DB_DATABASE)
db_obj = dbClass.DbWrapper(mysql_obj)


def valid_auth(auth_key):
    if auth_key != env.AUTH_KEY:
        return False
    return True


# Sensitive stuff, gonna be vague about var names here.
def cookie_check(up, ui):
    user_cookie = request.cookies.get('seohelper_user_cookie')
    if not user_cookie:
        return False
    else:
        if "&&" in user_cookie:
            cookie_up, cookie_ui = user_cookie.split("&&", 1)
            if up == cookie_up and ui == cookie_ui:
                return True
        return False


def get_hashed_password(plain_text_password):
    # Hash a password for the first time
    return bcrypt.hashpw(str(plain_text_password).encode('utf-8'), bcrypt.gensalt(12))


def check_password(plain_text_password, hashed_password):
    # Check hashed password. Using bcrypt, the salt is saved into the hash itself
    return bcrypt.checkpw(str(plain_text_password).encode('utf-8'), hashed_password.encode('utf-8'))


def process_xml(xml_str):
    url_array = []
    if len(xml_str) != "":
        root = ET.fromstring(xml_str)
        if root:
            for url in root.getchildren():
                url_array.append(url.getchildren()[0].text)
                # TODO: This should be addressed ASAP! Only works when 'loc' is the first child.
            return url_array
        else:
            print("Root is empty somehow.")
            return None
    else:
        print("xml_str is empty.")
        return None


@app.route('/api/login', methods=['POST'])
def action_user_login():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'POST':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)
                # Creating a user with given values.
                json_data = request.get_json()
                if 'email' in json_data and 'password' in json_data:
                    password = json_data['password']
                    email = json_data['email']

                    # TODO: Instead of 2 queries, make one single query.
                    # Checking if the user already exits.
                    checked_user_id = db_obj.exists('user', [('email', email)])
                    if checked_user_id:  # It exists.
                        checked_user = db_obj.get_data("user",
                                                       COLUMNS=["name_surname", "password", "email"],
                                                       WHERE=[{'init': {'id': checked_user_id}}],
                                                       OPERATOR="eq")[0]
                        checked_pass = checked_user['password']
                        passcheck = check_password(password, checked_pass)
                        if passcheck:
                            api_key = db_obj.get_data("api_key",
                                                      COLUMNS=["api_key"],
                                                      WHERE=[{'init': {'user_id': checked_user_id}}],
                                                      OPERATOR="eq")[0]['api_key']

                            response = make_response(jsonify({"redir-url": "/account/analyse",
                                                              "message": "You are being redirected now."}), 200)

                            response.set_cookie('seohelper_user_cookie', checked_pass + "&&" + str(checked_user_id),
                                                max_age=60 * 60 * 24)  # Age is 1 day.

                            response.set_cookie('seohelper_username',
                                                str(checked_user['name_surname']), max_age=60 * 60 * 24)
                            response.set_cookie('seohelper_usermail',
                                                str(checked_user['email']), max_age=60 * 60 * 24)
                            response.set_cookie('seohelper_userapikey',
                                                str(api_key), max_age=60 * 60 * 24)
                            return response
                        else:
                            # invalid password
                            return make_response(jsonify(
                                {
                                    "message": "Invalid password."}
                            ), 200)
                    else:
                        return make_response(jsonify(
                            {"message": "No user with given e-mail address."}), 200)
                else:
                    print(json_data)
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/user', methods=['POST', 'GET'])
def action_user():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'POST':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)
                # Creating a user with given values.
                json_data = request.get_json()
                if 'name_surname' in json_data and 'password' in json_data and 'email' in json_data:
                    name_surname = json_data['name_surname']
                    password = get_hashed_password(json_data['password']).decode("utf-8")
                    email = json_data['email']

                    # Checking if the user already exists.
                    checked_user_id = db_obj.exists('user', [('email', email)])
                    if checked_user_id:  # It exists.
                        return make_response(jsonify(
                            {"message": "There is already an existing user with this e-mail address."}), 200)
                    else:
                        try:
                            db_obj.insert_data('user',
                                               [(name_surname, password, email, time.time())],
                                               COLUMNS=['name_surname', 'password', 'email', 'created_at'])
                        except Exception as e:
                            print(e)
                            return make_response(jsonify(
                                {"message": "Action could not be performed. Query did not execute successfully."}), 500)

                        # Generating an API key assigned to the user id.
                        api_key = ''.join(secrets.token_hex(20))
                        userid = db_obj.get_last_insert_id()

                        try:
                            db_obj.insert_data('api_key',
                                               [(userid, api_key, time.time())],
                                               COLUMNS=['user_id', 'api_key', 'timestamp'])
                        except Exception as e:
                            print(e)
                            try:
                                db_obj.execute("DELETE FROM user WHERE user.id = " + userid + " LIMIT 1;")
                            except Exception as e:
                                print(e)
                                return make_response(jsonify(
                                    {"message": "Action could not be performed. Query did not execute successfully."}),
                                    500)
                            return make_response(jsonify(
                                {"message": "Action could not be performed. Query did not execute successfully."}), 500)

                        # Success!
                        return make_response(jsonify({
                            "message": "User is generated successfully!",
                            "User ID": userid,
                            "API Key:": api_key}), 200)
                else:
                    print(json_data)
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            elif request.method == 'GET':
                try:
                    userdata = db_obj.execute("SELECT * FROM user")
                except Exception as e:
                    print(e)
                    return make_response(jsonify(
                        {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                return make_response(jsonify(userdata), 200)
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/update-user', methods=['POST'])
def action_update_user():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'POST':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)
                # Creating a user with given values.
                json_data = request.get_json()
                if 'old_pw' in json_data and 'new_pw' in json_data and 'email' in json_data:
                    email = json_data['email']
                    old_pw = json_data['old_pw']
                    new_pw = json_data['new_pw']

                    # Checking if the user already exits.
                    checked_user_id = db_obj.exists('user', [('email', email)])
                    if checked_user_id:  # It exists.
                        checked_user = db_obj.get_data("user",
                                                       COLUMNS=["name_surname", "password", "email"],
                                                       WHERE=[{'init': {'id': checked_user_id}}],
                                                       OPERATOR="eq")[0]
                        checked_pass = checked_user['password']
                        passcheck = check_password(old_pw, checked_pass)
                        if passcheck:
                            # Pass is right, update with new password.
                            new_pw = get_hashed_password(new_pw).decode("utf-8")
                            try:
                                db_obj.execute(
                                    'UPDATE user SET password = "{0}" WHERE email = "{1}"'.format(new_pw, email))
                            except Exception as e:
                                print(e)
                                return make_response(jsonify(
                                    {"message": "Action could not be performed. Query did not execute successfully."}),
                                    500)
                            return make_response(jsonify(
                                {"message": "Password updated successfully!"}), 200)
                    return make_response(jsonify(
                        {"message": "Invalid password."}), 200)
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)
    return Response(status=401)


@app.route('/api/user-history', methods=['POST'])
def action_get_user_history():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            # JSON control.
            if not check_json(request):
                return make_response(jsonify(
                    {"message": "Request body must be JSON."}), 400)
            json_data = request.get_json()
            if 'api_key' in json_data:
                api_key = json_data['api_key']
                sql = "SELECT user_id FROM api_key WHERE api_key = '{0}';".format(api_key)
                user_id = db_obj.execute(sql)[0]['user_id']

                sql = """SELECT analysis_user.url_id, analysed_url.url,
                    analysis_user.time
                    FROM analysis_user 
                    JOIN analysed_url ON analysis_user.url_id = analysed_url.id
                    WHERE analysis_user.user_id = {0};""".format(user_id)
                url_time_array = db_obj.execute(sql)

                sql = """SELECT GROUP_CONCAT(seo_errors.name SEPARATOR '<br><br>') AS error_name,
                    analysis_user.url_id
                    FROM analysis_user
                    JOIN analysed_url ON analysis_user.url_id = analysed_url.id
                    JOIN analysis_errors ON analysis_errors.url_id = analysis_user.url_id
                    JOIN seo_errors ON analysis_errors.error_id = seo_errors.id
                    WHERE analysis_user.user_id = {0} GROUP BY analysed_url.url, analysis_user.url_id;""".format(
                    user_id)
                url_error_array = db_obj.execute(sql)

                for url_time in url_time_array:  # Bigger one.
                    url_id = url_time['url_id']
                    url_time['error_name'] = " - "
                    for url_error in url_error_array:
                        if url_id == url_error['url_id']:
                            url_time['error_name'] = url_error['error_name']

                return make_response(jsonify(url_time_array), 200)
            else:
                return make_response(jsonify(
                    {"message": "Invalid parameters."}), 400)
    return Response(status=401)


@app.route('/api/seo-errors/<int:error_id>', methods=['GET', 'DELETE'])
def action_get_seo_error(error_id):
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'GET':
                if error_id and error_id > 0:
                    try:
                        error_detail = db_obj.execute("SELECT * FROM seo_errors WHERE id = '" + str(error_id) + "';")
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    if len(error_detail) > 0:
                        return make_response(jsonify(error_detail), 200)
                    else:
                        return Response("No record found for this error ID.", status=404)
                else:
                    return Response("No record found for this error ID.", status=404)
            elif request.method == 'DELETE':
                if error_id and error_id > 0:
                    try:
                        query = db_obj.execute("DELETE FROM seo_errors WHERE id = '{0}' LIMIT 1".format(error_id))
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    return make_response(jsonify({"message": "Success!."}), 200)
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/seo-errors', methods=['POST', 'PUT', 'GET'])
def action_seo_errors():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.

            # POST
            if request.method == 'POST':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)

                # Creating a new SEO error with given name, description and error-condition.
                json_data = request.get_json()
                if 'name' in json_data and 'tag' in json_data:
                    print(json_data)
                    name = json_data['name']
                    tag = json_data['tag']
                    description = None if 'description' not in json_data else json_data['description']
                    attribute = None if 'attribute' not in json_data else json_data['attribute']
                    value = None if 'value' not in json_data else json_data['value']
                    content = None if 'content' not in json_data else json_data['content']

                    if attribute == "":
                        attribute = None
                    if value == "":
                        value = None
                    if content == "":
                        content = None

                    # Check for error duplication.
                    checked_error_id = db_obj.exists('seo_errors', [('tag', tag), ('attribute', attribute),
                                                                    ('value', value), ('content', content)])
                    if checked_error_id:
                        message = "There is already an existing SEO error associated with this tag!"
                        return make_response({"message": message}, 200)

                    try:
                        db_obj.insert_data('seo_errors',
                                           [(name, tag, description, attribute, value, content)],
                                           COLUMNS=['name', 'tag', 'description', 'attribute', 'value', 'content'])
                        message = "A new error has been added successfully!"
                    except Exception as e:
                        print(e)
                        message = "Action could not be performed. Query did not execute successfully."
                    return make_response({"message": message}, 200)
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            # PUT
            elif request.method == 'PUT':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)

                json_data = request.get_json()
                if 'id' in json_data and 'data' in json_data:
                    row_id = json_data['id']
                    update_items = json_data['data'].items()

                    try:
                        db_obj.update_data('seo_errors', update_items, row_id)
                        message = "Error with id #" + str(row_id) + " is updated successfully!"
                    except Exception as e:
                        print(traceback.format_exc() + "\n" + e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    return make_response(message, 200)
                return make_response(jsonify(
                    {"message": "Invalid parameters."}), 400)

            # GET
            elif request.method == 'GET':
                try:
                    error_detail = db_obj.execute("SELECT * FROM seo_errors")
                except Exception as e:
                    print(e)
                    return make_response(jsonify(
                        {"message": "Action could not be performed. Query did not execute successfully."}), 500)

                if len(error_detail) > 0:
                    return make_response(jsonify(error_detail), 200)
                else:
                    return Response("No record found for this error ID.", status=404)

            # 405
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/analysed-url/<int:url_id>', methods=['GET'])
def action_get_analysed_url(url_id):
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'GET':
                if url_id and url_id > 0:
                    try:
                        url_detail = db_obj.execute("SELECT * FROM analysed_url WHERE id = '" + str(url_id) + "';")
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    if len(url_detail) > 0:
                        return make_response(jsonify(url_detail), 200)
                    else:
                        return Response("No record found for this error ID.", status=404)
                else:
                    return Response("No record found for this error ID.", status=404)
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/analysed-url', methods=['POST', 'GET'])
def action_analysed_url():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.

            # JSON control.
            if not check_json(request):
                return make_response(jsonify(
                    {"message": "Request body must be JSON."}), 400)

            # POST
            if request.method == 'POST':
                # Creating a new record of analysed URL with given name, accessed-time.
                json_data = request.get_json()
                if 'url' in json_data and 'time_accessed' in json_data:
                    url = json_data['url']
                    extracted_url = tldextract.extract(url)
                    subdomain = extracted_url.subdomain
                    domain = extracted_url.domain
                    time_accessed = json_data['time_accessed']

                    try:
                        db_obj.insert_data('analysed_url',
                                           [(url, subdomain, domain, time_accessed)],
                                           COLUMNS=['url', 'subdomain', 'domain', 'time_accessed'])
                        message = "A new URL has been added successfully!"
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    return make_response(message, 200)
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            # GET
            elif request.method == 'GET':
                try:
                    analysis_detail = db_obj.execute("SELECT * FROM analysed_url")
                except Exception as e:
                    print(e)
                    return make_response(jsonify(
                        {"message": "Action could not be performed. Query did not execute successfully."}), 500)

                if len(analysis_detail) > 0:
                    return make_response(jsonify(analysis_detail), 200)
                else:
                    return Response("No record found for this error ID.", status=404)

            # 405
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/analysis-errors/<int:url_id>', methods=['GET'])
def action_get_analysis_errors(url_id):
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'GET':
                if url_id and url_id > 0:
                    try:
                        url_detail = db_obj.execute(
                            """SELECT analysis_errors.id, analysed_url.url, analysed_url.time_accessed, 
                            seo_errors.name, seo_errors.description FROM analysis_errors 
                            RIGHT JOIN analysed_url ON analysis_errors.url_id=analysed_url.id 
                            RIGHT JOIN seo_errors ON analysis_errors.error_id=seo_errors.id 
                            WHERE url_id = '""" + str(url_id) + "';")
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    if len(url_detail) > 0:
                        return make_response(jsonify(url_detail), 200)
                    else:
                        return Response("No record found for this error ID.", status=404)
                else:
                    return Response("No record found for this error ID.", status=404)
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/analysis-errors', methods=['POST', 'GET'])
def action_analysis_errors():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.

            # JSON control.
            if not check_json(request):
                return make_response(jsonify(
                    {"message": "Request body must be JSON."}), 400)

            # POST
            if request.method == 'POST':
                # Creating a new record of analysed URL with given name, accessed-time.
                json_data = request.get_json()
                if 'url_id' in json_data and 'error_id' in json_data:
                    url_id = json_data['url_id']
                    error_id = json_data['error_id']

                    try:
                        db_obj.insert_data('analysis_errors',
                                           [(url_id, error_id)],
                                           COLUMNS=['url_id', 'error_id'])
                        message = "A new URL & error match has been added successfully!"
                    except Exception as e:
                        print(e)
                        return make_response(jsonify(
                            {"message": "Action could not be performed. Query did not execute successfully."}), 500)
                    return make_response(message, 200)
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            # GET
            elif request.method == 'GET':
                try:
                    all_records = db_obj.execute(
                        """SELECT analysis_errors.id, analysed_url.url, analysed_url.time_accessed, 
                            seo_errors.name, seo_errors.description FROM analysis_errors 
                            JOIN analysed_url ON analysis_errors.url_id=analysed_url.id 
                            JOIN seo_errors ON analysis_errors.error_id=seo_errors.id;""")
                except Exception as e:
                    print(e)
                    return make_response(jsonify(
                        {"message": "Action could not be performed. Query did not execute successfully."}), 500)

                if len(all_records) > 0:
                    return make_response(jsonify(all_records), 200)
                else:
                    return make_response(jsonify(
                        {"message": "No record found for this error ID."}), 404)

            # 405
            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/api/analysis', methods=['POST'])
def request_analysis():
    # JSON control.
    if not check_json(request):
        return make_response(jsonify(
            {"message": "Request body must be JSON."}), 400)

    # POST
    if request.method == 'POST':
        json_data = request.get_json()
        if 'url' in json_data and 'api_key' in json_data:
            url = json_data['url']
            api_key = json_data['api_key']

            analyser = Analyser()

            if 'mode' in json_data:
                if json_data['mode'] == "domain":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "single",
                                                               dup_mode='domain', ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "single", dup_mode='domain')
                    else:
                        result = analyser.request_analysis(url, api_key, "single", dup_mode='domain')
                elif json_data['mode'] == "subdomain":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "single",
                                                               dup_mode='subdomain', ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "single", dup_mode='subdomain')
                    else:
                        result = analyser.request_analysis(url, api_key, "single", dup_mode='subdomain')
                elif json_data['mode'] == "default":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "single",
                                                               ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "single")
                    else:
                        result = analyser.request_analysis(url, api_key, "single")
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters." + json_data['mode']}), 400)
            else:
                result = analyser.request_analysis(url, api_key, "single")
            return make_response(result, 200)
        else:
            return make_response(jsonify(
                {"message": "Invalid parameters."}), 400)
    # 405
    else:
        return Response(status=405)


@app.route('/api/batch-analysis', methods=['POST'])
def request_analysis_batch():
    # JSON control.
    if not check_json(request):
        return make_response(jsonify(
            {"message": "Request body must be JSON."}), 400)

    # POST
    if request.method == 'POST':
        json_data = request.get_json()
        if 'url' in json_data and 'api_key' in json_data:
            url = json_data['url']
            api_key = json_data['api_key']

            # Check if a file has been sent. If it's an XML, get the URLs from there and append to url list.
            # Remember, for XML uploading, you need to send an empty array of 'url' as a data.
            if 'file' in json_data:
                xml_str = json_data['file']
                url.extend(process_xml(xml_str))  # Process XML, get xml-urls and add them to url list.

            analyser = Analyser()

            if 'mode' in json_data:
                if json_data['mode'] == "domain":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "batch",
                                                               dup_mode='domain', ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "batch", dup_mode='domain')
                    else:
                        result = analyser.request_analysis(url, api_key, "batch", dup_mode='domain')
                elif json_data['mode'] == "subdomain":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "batch",
                                                               dup_mode='subdomain', ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "batch", dup_mode='subdomain')
                    else:
                        result = analyser.request_analysis(url, api_key, "batch", dup_mode='subdomain')
                elif json_data['mode'] == "default":
                    if 'ignore' in json_data:
                        if len(json_data['ignore']) > 0:
                            result = analyser.request_analysis(url, api_key, "batch",
                                                               ignore_errors=json_data['ignore'])
                        else:
                            result = analyser.request_analysis(url, api_key, "batch")
                    else:
                        result = analyser.request_analysis(url, api_key, "batch")
                else:
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)
            else:
                result = analyser.request_analysis(url, api_key, "batch")
            return make_response(result, 200)
        else:
            return make_response(jsonify(
                {"message": "Invalid parameters."}), 400)
    # 405
    else:
        return Response(status=405)


@app.route('/check-connection', methods=['POST', 'GET'])
def check_connection():
    # Validate the request body contains JSON
    if request.is_json:
        req = request.get_json()
        res = make_response(jsonify({"message": "All okay!", "request": req}), 200)
        return res
    else:
        return make_response(jsonify({"message": "Request body must be JSON"}), 400)


@app.route('/test-analysis', methods=['GET'])
def test_analysis():
    return render_template("test_html.html")


@app.route('/test-301', methods=['GET'])
def test_301():
    return redirect(url_for('test_analysis'), 301)


def check_json(in_request):
    if in_request.is_json:
        return True
    else:
        return False


@app.route('/api', methods=['POST', 'GET'])
def api_test():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            return "API is working!", 200
    return Response("Unauthorized!", status=401)


@app.route('/sign-up', methods=['GET'])
def signup():
    return render_template("sign-up.html", Auth_Key=env.AUTH_KEY)


@app.route('/login', methods=['GET'])
def login():
    return render_template("login.html", Auth_Key=env.AUTH_KEY)


@app.route('/', methods=['GET'])
def index():
    return render_template("index.html", Auth_Key=env.AUTH_KEY)


@app.route('/logout', methods=['GET'])
def logout():
    user_cookie = request.cookies.get('seohelper_user_cookie')
    if user_cookie:
        # Cookie is existing, burn it.
        res = make_response(redirect(url_for('login')))
        res.set_cookie('seohelper_user_cookie', '', 0)
        res.set_cookie('seohelper_username', '', 0)
        res.set_cookie('seohelper_usermail', '', 0)
        res.set_cookie('seohelper_userapikey', '', 0)
        res.set_cookie('seohelper_adminstatus', '', 0)
        return res
    else:
        return redirect(url_for('login'))


@app.route('/account/analyse', methods=['GET'])
def account_analyse():
    user_cookie = request.cookies.get('seohelper_user_cookie')
    user_name = request.cookies.get('seohelper_username')
    user_api_key = request.cookies.get('seohelper_userapikey')
    if not user_cookie and not user_name and not user_api_key:
        return redirect(url_for('login'))
    else:
        return render_template("account/analyse.html", username=user_name, api_key=user_api_key, Auth_Key=env.AUTH_KEY)


@app.route('/account/history', methods=['GET'])
def account_history():
    user_cookie = request.cookies.get('seohelper_user_cookie')
    user_name = request.cookies.get('seohelper_username')
    user_api_key = request.cookies.get('seohelper_userapikey')
    if not user_cookie and not user_name and not user_api_key:
        return redirect(url_for('login'))
    else:
        return render_template("account/history.html", username=user_name, api_key=user_api_key, Auth_Key=env.AUTH_KEY)


@app.route('/account/settings', methods=['GET'])
def account_settings():
    user_cookie = request.cookies.get('seohelper_user_cookie')
    user_name = request.cookies.get('seohelper_username')
    user_mail = request.cookies.get('seohelper_usermail')
    user_api_key = request.cookies.get('seohelper_userapikey')
    if not user_cookie and not user_name and not user_api_key:
        return redirect(url_for('login'))
    else:
        return render_template("account/settings.html", username=user_name,
                               usermail=user_mail, api_key=user_api_key, Auth_Key=env.AUTH_KEY)


@app.route('/admin/login', methods=['POST'])
def action_admin_login():
    if 'Auth-Key' in request.headers:
        auth_key = request.headers['Auth-Key']
        if valid_auth(auth_key):  # Valid Auth Key, proceed as usual.
            if request.method == 'POST':

                # JSON control.
                if not check_json(request):
                    return make_response(jsonify(
                        {"message": "Request body must be JSON."}), 400)
                # Creating a user with given values.
                json_data = request.get_json()
                if 'email' in json_data and 'password' in json_data:
                    password = json_data['password']
                    email = json_data['email']

                    # Checking if the user already exits.
                    checked_user_id = db_obj.exists('user', [('email', email)])
                    if checked_user_id:  # It exists.
                        checked_user = db_obj.get_data("user",
                                                       COLUMNS=["name_surname", "password", "email"],
                                                       WHERE=[{'init': {'id': checked_user_id}}],
                                                       OPERATOR="eq")[0]
                        checked_pass = checked_user['password']
                        passcheck = check_password(password, checked_pass)
                        if passcheck:

                            # If checked user id is admin...
                            checked_admin = db_obj.exists('user_access_control', [('user_id', checked_user_id),
                                                                                  ('is_admin', 1)])
                            if checked_admin:
                                api_key = db_obj.get_data("api_key",
                                                          COLUMNS=["api_key"],
                                                          WHERE=[{'init': {'user_id': checked_user_id}}],
                                                          OPERATOR="eq")[0]['api_key']

                                response = make_response(jsonify({"redir-url": "/admin/manage",
                                                                  "message": "You are being redirected now."}), 200)

                                response.set_cookie('seohelper_user_cookie', checked_pass + "&&" + str(checked_user_id),
                                                    max_age=60 * 60 * 24)  # Age is 1 day.

                                response.set_cookie('seohelper_username',
                                                    str(checked_user['name_surname']), max_age=60 * 60 * 24)
                                response.set_cookie('seohelper_usermail',
                                                    str(checked_user['email']), max_age=60 * 60 * 24)
                                response.set_cookie('seohelper_userapikey',
                                                    str(api_key), max_age=60 * 60 * 24)
                                response.set_cookie('seohelper_adminstatus', "1", max_age=60*60)
                                return response
                            else:
                                return make_response(jsonify(
                                    {"message": "Given user account is not an admin."}), 200)
                        else:
                            # invalid password
                            return make_response(jsonify(
                                {
                                    "message": "Invalid password."}
                            ), 200)
                    else:
                        return make_response(jsonify(
                            {"message": "No admin with given e-mail address."}), 200)
                else:
                    print(json_data)
                    return make_response(jsonify(
                        {"message": "Invalid parameters."}), 400)

            else:
                return Response(status=405)
    return Response(status=401)


@app.route('/admin/login', methods=['GET'])
def admin_login():
    return render_template("admin/login.html", Auth_Key=env.AUTH_KEY)


@app.route('/admin/manage', methods=['GET'])
def admin_manage():
    user_cookie = request.cookies.get('seohelper_user_cookie')
    user_name = request.cookies.get('seohelper_username')
    user_mail = request.cookies.get('seohelper_usermail')
    user_api_key = request.cookies.get('seohelper_userapikey')
    user_admin_status = request.cookies.get('seohelper_adminstatus')
    if not user_cookie and not user_name and not user_api_key and user_admin_status is not "1":
        return redirect(url_for('admin_login'))
    else:
        return render_template("admin/manage.html", username=user_name,
                               usermail=user_mail, api_key=user_api_key, Auth_Key=env.AUTH_KEY)


@app.after_request
def add_header(r):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    r.headers["Cache-Control"] = "no-store"
    return r


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7070)
