import json
import os
import re
import urllib

import flask
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery
import requests

API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'
CLIENT_SECRETS_FILE = 'client_secret.json'
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']

app = flask.Flask(__name__)
app.secret_key = b'\xfb\x04\x088E6\xff\xd2\x86\x93\xcef%\x1b\xe6F9`o\xb8\xbd\xc3\xf3['

@app.route('/')
def index(user = None):
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    return flask.render_template('index.html', user = flask.session['user'])

@app.route('/channels')
def channels(user = None, subs = None, tracks = [], tracking = False, error = False):
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    if 'channels_query_error' in flask.session:
        error = flask.session.pop('channels_query_error')

    return flask.render_template('channels.html', user = flask.session['user'],
        subs = yt_get_subscriptions(list_only = True), tracks = yt_get_tracks(),
        tracking = tracking, error = error)

@app.route('/channels-track')
def channels_track(user = None, subs = [], tracks = [], tracking = True, error = False):
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    return flask.render_template('channels.html', user = flask.session['user'],
        subs = yt_get_subscriptions(), tracks = db_get_channels(),
        tracking = tracking, error = error)

@app.route('/channels-update')
def channels_update():
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    db = get_db()
    tracks = flask.request.args.get('tracks', None)
    query = flask.request.args.get('query', None)

    if tracks is not None:
        for channel_id, tracked in json.loads(urllib.parse.unquote(tracks)).items():
            if tracked:
                if channel_id not in db[flask.session['user']['id']]:
                    db[flask.session['user']['id']][channel_id] = {}
            else:
                if channel_id in db[flask.session['user']['id']]:
                    db[flask.session['user']['id']].pop(channel_id)

    if query is not None:
        client = yt_get_client()
        query_data = json.loads(urllib.parse.unquote(query))

        try:
            if query_data['type'] == 'url':
                url = query_data['value']
                if '/user/' in url:
                    user = re.search('^.+\/user\/([^\/]+)(\/.*|$)', url, re.IGNORECASE).group(1)
                    response = client.channels().list(
                        part = 'snippet', forUsername = user
                    ).execute()
                    db[flask.session['user']['id']][response['items'][0]['id']] = {}
                elif '/channel/' in url:
                    channel_id = url.rsplit('/', 1)[-1]
                    response = client.channels().list(
                        part = 'snippet', id = channel_id
                    ).execute()
                    db[flask.session['user']['id']][response['items'][0]['id']] = {}
                else:
                    raise
            elif query_data['type'] == 'user':
                response = client.channels().list(
                    part = 'snippet', forUsername = query_data['value']
                ).execute()
                db[flask.session['user']['id']][response['items'][0]['id']] = {}
            elif query_data['type'] == 'id':
                response = client.channels().list(
                    part = 'snippet', id = query_data['value']
                ).execute()
                db[flask.session['user']['id']][response['items'][0]['id']] = {}
        except:
            flask.session['channels_query_error'] = True
            return flask.redirect('channels')

    update_db(db)

    return flask.redirect('channels')

@app.route('/channels-subscriptions')
def channels_subscriptions():
    if 'credentials' not in flask.session:
        return flask.redirect('authorize')

    client = yt_get_client()
    update = flask.request.args.get('update', None)

    if update is not None:
        update_data = json.loads(urllib.parse.unquote(update))

        if update_data['subscribe']:
            client.subscriptions().insert(
                body = build_resource({
                    'snippet.resourceId.kind': 'youtube#channel',
                    'snippet.resourceId.channelId': update_data['id']
                }),
                part = 'snippet'
            ).execute()
        else:
            client.subscriptions().delete(
                id = update_data['id']
            ).execute()

        return flask.redirect(update_data['redirect'])

    return flask.redirect('channels')

def get_db():
    return json.load(open('db.json'))

def update_db(db):
    with open('db.json', 'w') as f:
        json.dump(db, f, indent = 2, sort_keys = True)

def db_get_channels():
    db = get_db()
    return list(db[flask.session['user']['id']].keys())

def yt_get_user():
    client = yt_get_client()
    response = client.channels().list(part = 'snippet', mine = True).execute()
    snippet = response['items'][0]['snippet']
    return {
        'thumbnail': snippet['thumbnails']['default']['url'],
        'name': snippet['title'],
        'id': response['items'][0]['id']
    }

def yt_get_subscriptions(list_only = False):
    client = yt_get_client()
    kwargs = {
        'part': 'snippet', 'mine': True,
        'order': 'alphabetical', 'maxResults': 50
    }

    if list_only:
        items = {}
    else:
        items = []

    while True:
        response = client.subscriptions().list(**kwargs).execute()

        for item in response['items']:
            if list_only:
                items[item['snippet']['resourceId']['channelId']] = item['id']
            else:
                items.append(item)

        if 'nextPageToken' not in response:
            return items
        else:
            kwargs['pageToken'] = response['nextPageToken']

def yt_get_tracks():
    tracks = []

    for channel_id in db_get_channels():
        client = yt_get_client()
        response = client.channels().list(
            part = 'snippet', id = channel_id
        ).execute()
        tracks.append(response['items'][0])

    return sorted(tracks, key = lambda item: item['snippet']['title'])

def yt_get_client():
    credentials = google.oauth2.credentials.Credentials(
        **flask.session['credentials']
    )

    return googleapiclient.discovery.build(
        API_SERVICE_NAME, API_VERSION, credentials = credentials
    )

def build_resource(properties):
    resource = {}
    for p in properties:
        # Given a key like "snippet.title", split into "snippet" and "title", where
        # "snippet" will be an object and "title" will be a property in that object.
        prop_array = p.split('.')
        ref = resource
        for pa in range(0, len(prop_array)):
            is_array = False
            key = prop_array[pa]
            
            # For properties that have array values, convert a name like
            # "snippet.tags[]" to snippet.tags, and set a flag to handle
            # the value as an array.
            if key[-2:] == '[]':
                key = key[0:len(key)-2:]
                is_array = True

            if pa == (len(prop_array) - 1):
                # Leave properties without values out of inserted resource.
               if properties[p]:
                   if is_array:
                       ref[key] = properties[p].split(',')
                   else:
                       ref[key] = properties[p]
            elif key not in ref:
                # For example, the property is "snippet.title", but the resource does
                # not yet have a "snippet" object. Create the snippet object here.
                # Setting "ref = ref[key]" means that in the next time through the
                # "for pa in range ..." loop, we will be setting a property in the
                # resource's "snippet" object.
                ref[key] = {}
                ref = ref[key]
            else:
                # For example, the property is "snippet.description", and the resource
                # already has a "snippet" object.
                ref = ref[key]
    return resource

@app.route('/authorize')
def authorize():
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes = SCOPES
    )
    flow.redirect_uri = flask.url_for('oauth2callback', _external = True)

    authorization_url, state = flow.authorization_url(
        access_type = 'offline',
        include_granted_scopes = 'true'
    )

    flask.session['state'] = state

    return flask.redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    state = flask.session['state']

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes = SCOPES, state = state
    )
    flow.redirect_uri = flask.url_for('oauth2callback', _external = True)

    authorization_response = flask.request.url
    flow.fetch_token(authorization_response = authorization_response)

    credentials = flow.credentials
    flask.session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    flask.session['user'] = yt_get_user()

    db = get_db()
    if flask.session['user']['id'] not in db:
        db[flask.session['user']['id']] = {}
    update_db(db)

    return flask.redirect(flask.url_for('index'))

@app.route('/logout')
def logout():
    flask.session.clear()
    return flask.redirect('')

if __name__ == '__main__':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' # TODO: rm in production
    if not os.path.isfile('db.json'):
        with open('db.json', 'w') as f:
            json.dump({}, f, indent = 2, sort_keys = True)
    app.run('localhost', 8090, debug = True)