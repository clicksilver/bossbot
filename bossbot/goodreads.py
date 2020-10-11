from time import sleep
from xml.etree import ElementTree

import requests
from discord import Colour
from discord import Embed
from requests_oauthlib import OAuth1
from requests_oauthlib import OAuth1Session

from bossbot.db import GoodReadsDB


class GoodReadsAPI:
    base_url = 'https://www.goodreads.com/'

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()

    def get(self, *args, **kwargs):
        args = (self.base_url + args[0], *args[1:])
        if 'params' in kwargs:
            kwargs['params']['key'] = self.api_key
        else:
            kwargs['params'] = {}
            kwargs['params']['key'] = self.api_key
        resp = requests.get(*args, **kwargs)
        print(resp.text)
        return ElementTree.fromstring(resp.text)

    def start_oauth(self):
        o_sess = OAuth1Session(self.api_key, client_secret=self.api_secret)

        fetch_resp = o_sess.fetch_request_token(f'{self.base_url}oauth/request_token')
        oauth_token = fetch_resp.get('oauth_token')
        oauth_secret = fetch_resp.get('oauth_token_secret')

        authorization_url = o_sess.authorization_url(f'{self.base_url}oauth/authorize')
        return authorization_url, oauth_token, oauth_secret

    def finish_oauth(self, oauth_token, oauth_secret):
        oauth_access_session = OAuth1Session(
            self.api_key,
            client_secret=self.api_secret,
            resource_owner_key=oauth_token,
            resource_owner_secret=oauth_secret,
        )
        access_token_url = f'{self.base_url}oauth/access_token'
        access_token = oauth_access_session._fetch_token(access_token_url)
        return access_token['oauth_token'], access_token['oauth_token_secret']

    def get_currently_reading(self, username, oauth_token, oauth_token_secret):
        resp = self.get('user/show', params={'username': username})
        user_id = resp.find('user').find('id').text

        return self.get(
            'review/list',
            auth=OAuth1(
                self.api_key, self.api_secret,
                oauth_token, oauth_token_secret,
            ),
            params={'v': 2, 'format': 'xml', 'id': user_id, 'shelf': 'currently-reading'},
        )


async def start_gr_oauth(bot, message):
    db = GoodReadsDB()
    gr = GoodReadsAPI(
        bot.config['goodreads']['API_KEY'],
        bot.config['goodreads']['API_SECRET'],
    )
    gr_user = message.content.split()[1]

    auth_link, oauth_token, oauth_secret = gr.start_oauth()
    db.store_tmp_gr_oauth(message.author.id, gr_user, oauth_token, oauth_secret)

    await message.channel.send(f'Follow this link and authorize bossbot to retrieve data for your account: {auth_link}')
    await message.channel.send(f'Once you\'ve done that, respond here with `finish-gr-oauth`')


async def finish_gr_oauth(bot, message):
    db = GoodReadsDB()
    gr = GoodReadsAPI(
        bot.config['goodreads']['API_KEY'],
        bot.config['goodreads']['API_SECRET'],
    )
    try:
        _, gr_username, oauth_token, oauth_secret = db.pop_tmp_gr_oauth(message.author.id)
        access_token, access_secret = gr.finish_oauth(oauth_token, oauth_secret)
        db.add_gr_user_oauth_access(message.author.id, gr_username, access_token, access_secret)
    except Exception as e:
        await message.channel.send('ugh gross, we failed')
        raise
    else:
        await message.channel.send('oauth complete!')


async def handle_gr_reading(bot, message):
    await message.add_reaction('📖')
    db = GoodReadsDB()
    gr = GoodReadsAPI(
        bot.config['goodreads']['API_KEY'],
        bot.config['goodreads']['API_SECRET'],
    )
    _, user, user_token, user_secret = db.fetch_user_oauth_access(message.author.id)
    resp = gr.get_currently_reading(user, user_token, user_secret)

    reading_embeds = []
    for book in resp.iterfind('.//book'):
        author = book.find('./authors/author/name').text
        pub_year = book.find('./publication_year').text
        description = book.find('./description').text[:1500]
        rating = book.find('./average_rating').text
        ratings_count = book.find('./ratings_count').text
        book_embed = Embed(
            title=book.find('title').text,
            description=f'by {author} ({pub_year})',
            url=book.find('link').text,
            colour=Colour.from_rgb(135, 89, 39),
        )
        book_embed.add_field(name='Description (may contain spoilers!)', value=f'||{description}||')
        book_embed.add_field(name='Rating', value=f'Rated **{rating}/5** based on {ratings_count} ratings', inline=True)
        book_embed.set_image(url=book.find('image_url').text)
        book_embed.set_footer(
            text='Provided by Goodreads™',
            icon_url='https://s.gr-assets.com/assets/icons/goodreads_icon_32x32-6c9373254f526f7fdf2980162991a2b3.png'
        )
        reading_embeds.append(book_embed)

    if reading_embeds:
        await message.channel.send(f'<@!{message.author.id}> is currently reading:', embed=reading_embeds[0])
        reading_embeds  = reading_embeds[1:]
        for next_embed in reading_embeds:
            await message.channel.send('', embed=next_embed)
    else:
        await message.channel.send('<@!{message.author.id}> is not currently reading anything! (did you DM me `gr-oauth` yet?)')
