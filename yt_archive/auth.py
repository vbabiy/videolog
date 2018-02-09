import flask
import google_auth_oauthlib.flow
import requests

from yt_archive.constants import CLIENT_SECRETS_FILE, SCOPES
from yt_archive.db import get_db, update_db
from yt_archive.youtube import yt_get_user

def auth_authorize():
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

def auth_oauth2callback():
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

def auth_check():
    if 'credentials' not in flask.session:
        raise Exception('authorize')
    else:
        if 'token' in flask.session['credentials']:
            base_url = 'https://www.googleapis.com/oauth2/v3/tokeninfo?access_token='
            response = requests.get(base_url + flask.session['credentials']['token'])
            if response.status_code == 400:
                raise Exception('logout')
        else:
            raise Exception('logout')

def auth_logout():
    flask.session.clear()
    return flask.redirect('')