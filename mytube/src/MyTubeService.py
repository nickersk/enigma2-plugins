# -*- coding: iso-8859-1 -*-
from __future__ import print_function
from __future__ import absolute_import
from enigma import ePythonMessagePump

from .__init__ import decrypt_block
from .ThreadQueue import ThreadQueue
import gdata.youtube
import gdata.youtube.service
from gdata.service import BadAuthentication

from twisted.web import client
from twisted.internet import reactor
from socket import gaierror, error
import os
import socket
import httplib
import re
import json
from six.moves.urllib.parse import quote, unquote_plus, unquote, urlencode, parse_qs, parse_qsl
from six.moves.urllib.request import Request, urlopen, URLError

from threading import Thread

import six
from six.moves.http_client import HTTPConnection, CannotSendRequest, BadStatusLine, HTTPException


HTTPConnection.debuglevel = 1

if 'HTTPSConnection' not in dir(httplib):
	# python on enimga2 has no https socket support
	gdata.youtube.service.YOUTUBE_USER_FEED_URI = 'http://gdata.youtube.com/feeds/api/users'


def validate_cert(cert, key):
	buf = decrypt_block(cert[8:], key)
	if buf is None:
		return None
	return buf[36:107] + cert[139:196]


def get_rnd():
	try:
		rnd = os.urandom(8)
		return rnd
	except:
		return None


std_headers = {
	'User-Agent': 'Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.2.6) Gecko/20100627 Firefox/3.6.6',
	'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
	'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
	'Accept-Language': 'en-us,en;q=0.5',
}

#config.plugins.mytube = ConfigSubsection()
#config.plugins.mytube.general = ConfigSubsection()
#config.plugins.mytube.general.useHTTPProxy = ConfigYesNo(default = False)
#config.plugins.mytube.general.ProxyIP = ConfigIP(default=[0,0,0,0])
#config.plugins.mytube.general.ProxyPort = ConfigNumber(default=8080)
#class MyOpener(FancyURLopener):
#	version = 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.8.0.12) Gecko/20070731 Ubuntu/dapper-security Firefox/1.5.0.12'


def printDBG(s):
    print(s)

# source from https://github.com/rg3/youtube-dl/issues/1208


class CVevoSignAlgoExtractor:
    # MAX RECURSION Depth for security
    MAX_REC_DEPTH = 5

    def __init__(self):
        self.algoCache = {}
        self._cleanTmpVariables()

    def _cleanTmpVariables(self):
        self.fullAlgoCode = ''
        self.allLocalFunNamesTab = []
        self.playerData = ''

    def _jsToPy(self, jsFunBody):
        pythonFunBody = jsFunBody.replace('function', 'def').replace('{', ':\n\t').replace('}', '').replace(';', '\n\t').replace('var ', '')
        pythonFunBody = pythonFunBody.replace('.reverse()', '[::-1]')

        lines = pythonFunBody.split('\n')
        for i in range(len(lines)):
            # a.split("") -> list(a)
            match = re.search('(\w+?)\.split\(""\)', lines[i])
            if match:
                lines[i] = lines[i].replace(match.group(0), 'list(' + match.group(1) + ')')
            # a.length -> len(a)
            match = re.search('(\w+?)\.length', lines[i])
            if match:
                lines[i] = lines[i].replace(match.group(0), 'len(' + match.group(1) + ')')
            # a.slice(3) -> a[3:]
            match = re.search('(\w+?)\.slice\(([0-9]+?)\)', lines[i])
            if match:
                lines[i] = lines[i].replace(match.group(0), match.group(1) + ('[%s:]' % match.group(2)))
            # a.join("") -> "".join(a)
            match = re.search('(\w+?)\.join\(("[^"]*?")\)', lines[i])
            if match:
                lines[i] = lines[i].replace(match.group(0), match.group(2) + '.join(' + match.group(1) + ')')
        return "\n".join(lines)

    def _getLocalFunBody(self, funName):
        # get function body
        match = re.search('(function %s\([^)]+?\){[^}]+?})' % funName, self.playerData)
        if match:
            # return jsFunBody
            return match.group(1)
        return ''

    def _getAllLocalSubFunNames(self, mainFunBody):
        match = re.compile('[ =(,](\w+?)\([^)]*?\)').findall(mainFunBody)
        if len(match):
            # first item is name of main function, so omit it
            funNameTab = set(match[1:])
            return funNameTab
        return set()

    def decryptSignature(self, s, playerUrl):
        playerUrl = playerUrl[:4] != 'http' and 'http:' + playerUrl or playerUrl
        printDBG("decrypt_signature sign_len[%d] playerUrl[%s]" % (len(s), playerUrl))

        # clear local data
        self._cleanTmpVariables()

        # use algoCache
        if playerUrl not in self.algoCache:
            # get player HTML 5 sript
            request = Request(playerUrl)
            try:
                self.playerData = urlopen(request).read()
                self.playerData = self.playerData.decode('utf-8', 'ignore')
            except:
                printDBG('Unable to download playerUrl webpage')
                return ''

            # get main function name
            match = re.search("signature=(\w+?)\([^)]\)", self.playerData)
            if match:
                mainFunName = match.group(1)
                printDBG('Main signature function name = "%s"' % mainFunName)
            else:
                printDBG('Can not get main signature function name')
                return ''

            self._getfullAlgoCode(mainFunName)

            # wrap all local algo function into one function extractedSignatureAlgo()
            algoLines = self.fullAlgoCode.split('\n')
            for i in range(len(algoLines)):
                algoLines[i] = '\t' + algoLines[i]
            self.fullAlgoCode = 'def extractedSignatureAlgo(param):'
            self.fullAlgoCode += '\n'.join(algoLines)
            self.fullAlgoCode += '\n\treturn %s(param)' % mainFunName
            self.fullAlgoCode += '\noutSignature = extractedSignatureAlgo( inSignature )\n'

            # after this function we should have all needed code in self.fullAlgoCode

            printDBG("---------------------------------------")
            printDBG("|    ALGO FOR SIGNATURE DECRYPTION    |")
            printDBG("---------------------------------------")
            printDBG(self.fullAlgoCode)
            printDBG("---------------------------------------")

            try:
                algoCodeObj = compile(self.fullAlgoCode, '', 'exec')
            except:
                printDBG('decryptSignature compile algo code EXCEPTION')
                return ''
        else:
            # get algoCodeObj from algoCache
            printDBG('Algo taken from cache')
            algoCodeObj = self.algoCache[playerUrl]

        # for security alow only flew python global function in algo code
        vGlobals = {"__builtins__": None, 'len': len, 'list': list}

        # local variable to pass encrypted sign and get decrypted sign
        vLocals = {'inSignature': s, 'outSignature': ''}

        # execute prepared code
        try:
            exec(algoCodeObj, vGlobals, vLocals)
        except:
            printDBG('decryptSignature exec code EXCEPTION')
            return ''

        printDBG('Decrypted signature = [%s]' % vLocals['outSignature'])
        # if algo seems ok and not in cache, add it to cache
        if playerUrl not in self.algoCache and '' != vLocals['outSignature']:
            printDBG('Algo from player [%s] added to cache' % playerUrl)
            self.algoCache[playerUrl] = algoCodeObj

        # free not needed data
        self._cleanTmpVariables()

        return vLocals['outSignature']

    # Note, this method is using a recursion
    def _getfullAlgoCode(self, mainFunName, recDepth=0):
        if self.MAX_REC_DEPTH <= recDepth:
            printDBG('_getfullAlgoCode: Maximum recursion depth exceeded')
            return

        funBody = self._getLocalFunBody(mainFunName)
        if '' != funBody:
            funNames = self._getAllLocalSubFunNames(funBody)
            if len(funNames):
                for funName in funNames:
                    if funName not in self.allLocalFunNamesTab:
                        self.allLocalFunNamesTab.append(funName)
                        printDBG("Add local function %s to known functions" % mainFunName)
                        self._getfullAlgoCode(funName, recDepth + 1)

            # conver code from javascript to python
            funBody = self._jsToPy(funBody)
            self.fullAlgoCode += '\n' + funBody + '\n'
        return


decryptor = CVevoSignAlgoExtractor()


class GoogleSuggestions():
	def __init__(self):
		self.hl = "en"
		self.conn = None

	def prepareQuery(self):
		#GET /complete/search?output=toolbar&client=youtube-psuggest&xml=true&ds=yt&hl=en&jsonp=self.gotSuggestions&q=s
		#self.prepQuerry = "/complete/search?output=toolbar&client=youtube&xml=true&ds=yt&"
		self.prepQuerry = "/complete/search?output=chrome&client=chrome&"
		if self.hl is not None:
			self.prepQuerry = self.prepQuerry + "hl=" + self.hl + "&"
		self.prepQuerry = self.prepQuerry + "jsonp=self.gotSuggestions&q="
		print("[MyTube - GoogleSuggestions] prepareQuery:", self.prepQuerry)

	def getSuggestions(self, queryString):
		self.prepareQuery()
		if queryString != "":
			query = self.prepQuerry + quote(queryString)
			self.conn = HTTPConnection("google.com")
			try:
				self.conn = HTTPConnection("google.com")
				self.conn.request("GET", query, "", {"Accept-Encoding": "UTF-8"})
			except (CannotSendRequest, gaierror, error):
				self.conn.close()
				print("[MyTube - GoogleSuggestions] Can not send request for suggestions")
				return None
			else:
				try:
					response = self.conn.getresponse()
				except BadStatusLine:
					self.conn.close()
					print("[MyTube - GoogleSuggestions] Can not get a response from google")
					return None
				else:
					if response.status == 200:
						data = response.read()
						header = response.getheader("Content-Type", "text/xml; charset=ISO-8859-1")
						charset = "ISO-8859-1"
						try:
							charset = header.split(";")[1].split("=")[1]
							print("[MyTube - GoogleSuggestions] Got charset %s" % charset)
						except:
							print("[MyTube - GoogleSuggestions] No charset in Header, falling back to %s" % charset)
						data = data.decode(charset).encode("utf-8")
						self.conn.close()
						return data
					else:
						self.conn.close()
						return None
		else:
			return None


class MyTubeFeedEntry():
	def __init__(self, feed, entry, favoritesFeed=False):
		self.feed = feed
		self.entry = entry
		self.favoritesFeed = favoritesFeed
		self.thumbnail = {}
		"""self.myopener = MyOpener()
		urllib.urlopen = MyOpener().open
		if config.plugins.mytube.general.useHTTPProxy.value is True:
			proxy = {'http': 'http://'+str(config.plugins.mytube.general.ProxyIP.getText())+':'+str(config.plugins.mytube.general.ProxyPort.value)}
			self.myopener = MyOpener(proxies=proxy)
			urllib.urlopen = MyOpener(proxies=proxy).open
		else:
			self.myopener = MyOpener()
			urllib.urlopen = MyOpener().open"""

	def isPlaylistEntry(self):
		return False

	def getTubeId(self):
		#print "[MyTubeFeedEntry] getTubeId"
		ret = None
		if self.entry.media.player:
			split = self.entry.media.player.url.split("=")
			ret = split.pop()
			if ret.startswith('youtube_gdata'):
				tmpval = split.pop()
				if tmpval.endswith("&feature"):
					tmp = tmpval.split("&")
					ret = tmp.pop(0)
		return ret

	def getTitle(self):
		#print "[MyTubeFeedEntry] getTitle",self.entry.media.title.text
		return self.entry.media.title.text

	def getDescription(self):
		#print "[MyTubeFeedEntry] getDescription"
		if self.entry.media is not None and self.entry.media.description is not None:
			return self.entry.media.description.text
		return "not vailable"

	def getThumbnailUrl(self, index=0):
		#print "[MyTubeFeedEntry] getThumbnailUrl"
		if index < len(self.entry.media.thumbnail):
			return self.entry.media.thumbnail[index].url
		return None

	def getPublishedDate(self):
		if self.entry.published is not None:
			return self.entry.published.text
		return "unknown"

	def getViews(self):
		if self.entry.statistics is not None:
			return self.entry.statistics.view_count
		return "not available"

	def getDuration(self):
		if self.entry.media is not None and self.entry.media.duration is not None:
			return self.entry.media.duration.seconds
		else:
			return 0

	def getRatingAverage(self):
		if self.entry.rating is not None:
			return self.entry.rating.average
		return 0

	def getNumRaters(self):
		if self.entry.rating is not None:
			return self.entry.rating.num_raters
		return ""

	def getAuthor(self):
		authors = []
		for author in self.entry.author:
			authors.append(author.name.text)
		author = ", ".join(authors)
		return author

	def getUserFeedsUrl(self):
		for author in self.entry.author:
			return author.uri.text

		return False

	def getUserId(self):
		return self.getUserFeedsUrl().split('/')[-1]

	def subscribeToUser(self):
		username = self.getUserId()
		return myTubeService.SubscribeToUser(username)

	def addToFavorites(self):
		video_id = self.getTubeId()
		return myTubeService.addToFavorites(video_id)

	def PrintEntryDetails(self):
		EntryDetails = {'Title': None, 'TubeID': None, 'Published': None, 'Published': None, 'Description': None, 'Category': None, 'Tags': None, 'Duration': None, 'Views': None, 'Rating': None, 'Thumbnails': None}
		EntryDetails['Title'] = self.entry.media.title.text
		EntryDetails['TubeID'] = self.getTubeId()
		EntryDetails['Description'] = self.getDescription()
		EntryDetails['Category'] = self.entry.media.category[0].text
		EntryDetails['Tags'] = self.entry.media.keywords.text
		EntryDetails['Published'] = self.getPublishedDate()
		EntryDetails['Views'] = self.getViews()
		EntryDetails['Duration'] = self.getDuration()
		EntryDetails['Rating'] = self.getNumRaters()
		EntryDetails['RatingAverage'] = self.getRatingAverage()
		EntryDetails['Author'] = self.getAuthor()
		# show thumbnails
		list = []
		for thumbnail in self.entry.media.thumbnail:
			print('Thumbnail url: %s' % thumbnail.url)
			list.append(str(thumbnail.url))
		EntryDetails['Thumbnails'] = list
		#print EntryDetails
		return EntryDetails

	def removeAdditionalEndingDelimiter(self, data):
		pos = data.find("};")
		if pos != -1:
			data = data[:pos + 1]
		return data

	def extractFlashVars(self, data, assets):
		flashvars = {}
		found = False

		for line in data.split("\n"):
			if line.strip().find(";ytplayer.config = ") > 0:
				found = True
				p1 = line.find(";ytplayer.config = ") + len(";ytplayer.config = ") - 1
				p2 = line.rfind(";")
				if p1 <= 0 or p2 <= 0:
					continue
				data = line[p1 + 1:p2]
				break
		data = self.removeAdditionalEndingDelimiter(data)

		if found:
			data = json.loads(data)
			if assets:
				flashvars = data["assets"]
			else:
				flashvars = data["args"]
		return flashvars

	# link resolving from xbmc youtube plugin
	def getVideoUrl(self):
		VIDEO_FMT_PRIORITY_MAP = {
			'38': 1, #MP4 Original (HD)
			'37': 2, #MP4 1080p (HD)
			'22': 3, #MP4 720p (HD)
			'18': 4, #MP4 360p
			'35': 5, #FLV 480p
			'34': 6, #FLV 360p
		}
		video_url = None
		video_id = str(self.getTubeId())

		links = {}
		watch_url = 'http://www.youtube.com/watch?v=%s&safeSearch=none' % video_id
		watchrequest = Request(watch_url, None, std_headers)

		try:
			print("[MyTube] trying to find out if a HD Stream is available", watch_url)
			result = urlopen(watchrequest).read()
		except (URLError, HTTPException, socket.error) as err:
			print("[MyTube] Error: Unable to retrieve watchpage - Error code: ", str(err))
			return video_url

		# Get video info
		for el in ['&el=embedded', '&el=detailpage', '&el=vevo', '']:
			info_url = ('http://www.youtube.com/get_video_info?&video_id=%s%s&ps=default&eurl=&gl=US&hl=en' % (video_id, el))
			request = Request(info_url, None, std_headers)
			try:
				infopage = urlopen(request).read()
				videoinfo = parse_qs(infopage)
				if ('url_encoded_fmt_stream_map' or 'fmt_url_map') in videoinfo:
					break
			except (URLError, HTTPException, socket.error) as err:
				print("[MyTube] Error: unable to download video infopage", str(err))
				return video_url

		if ('url_encoded_fmt_stream_map' or 'fmt_url_map') not in videoinfo:
			# Attempt to see if YouTube has issued an error message
			if 'reason' not in videoinfo:
				print('[MyTube] Error: unable to extract "fmt_url_map" or "url_encoded_fmt_stream_map" parameter for unknown reason')
			else:
				reason = unquote_plus(videoinfo['reason'][0])
				print('[MyTube] Error: YouTube said: %s' % reason.decode('utf-8'))
			return video_url

		video_fmt_map = {}
		fmt_infomap = {}
		if 'url_encoded_fmt_stream_map' in videoinfo:
			tmp_fmtUrlDATA = videoinfo['url_encoded_fmt_stream_map'][0].split(',')
		else:
			tmp_fmtUrlDATA = videoinfo['fmt_url_map'][0].split(',')
		for fmtstring in tmp_fmtUrlDATA:
			fmturl = fmtid = ""
			if 'url_encoded_fmt_stream_map' in videoinfo:
				try:
					for arg in fmtstring.split('&'):
						if arg.find('=') >= 0:
							key, value = arg.split('=')
							if key == 'itag':
								if len(value) > 3:
									value = value[:2]
								fmtid = value
							elif key == 'url':
								fmturl = value

					if fmtid != "" and fmturl != "" and fmtid in VIDEO_FMT_PRIORITY_MAP:
						video_fmt_map[VIDEO_FMT_PRIORITY_MAP[fmtid]] = {'fmtid': fmtid, 'fmturl': unquote_plus(fmturl)}
						fmt_infomap[int(fmtid)] = "%s" % (unquote_plus(fmturl))
					fmturl = fmtid = ""

				except:
					print("error parsing fmtstring:", fmtstring)

			else:
				(fmtid, fmturl) = fmtstring.split('|')
			if fmtid in VIDEO_FMT_PRIORITY_MAP and fmtid != "":
				video_fmt_map[VIDEO_FMT_PRIORITY_MAP[fmtid]] = {'fmtid': fmtid, 'fmturl': unquote_plus(fmturl)}
				fmt_infomap[int(fmtid)] = unquote_plus(fmturl)
		print("[MyTube] got", sorted(six.iterkeys(fmt_infomap)))
		if video_fmt_map and len(video_fmt_map):
			print("[MyTube] found best available video format:", video_fmt_map[sorted(six.iterkeys(video_fmt_map))[0]]['fmtid'])
			best_video = video_fmt_map[sorted(six.iterkeys(video_fmt_map))[0]]
			video_url = "%s" % (best_video['fmturl'].split(';')[0])
			print("[MyTube] found best available video url:", video_url)

		return video_url

	def getRelatedVideos(self):
		print("[MyTubeFeedEntry] getRelatedVideos()")
		for link in self.entry.link:
			#print "Related link: ", link.rel.endswith
			if link.rel.endswith("video.related"):
				print("Found Related: ", link.href)
				return link.href

	def getResponseVideos(self):
		print("[MyTubeFeedEntry] getResponseVideos()")
		for link in self.entry.link:
			#print "Responses link: ", link.rel.endswith
			if link.rel.endswith("video.responses"):
				print("Found Responses: ", link.href)
				return link.href

	def getUserVideos(self):
		print("[MyTubeFeedEntry] getUserVideos()")
		username = self.getUserId()
		myuri = 'http://gdata.youtube.com/feeds/api/users/%s/uploads' % username
		print("Found Uservideos: ", myuri)
		return myuri


class MyTubePlayerService():
#	Do not change the client_id and developer_key in the login-section!
#	ClientId: ytapi-dream-MyTubePlayer-i0kqrebg-0
#	DeveloperKey: AI39si4AjyvU8GoJGncYzmqMCwelUnqjEMWTFCcUtK-VUzvWygvwPO-sadNwW5tNj9DDCHju3nnJEPvFy4WZZ6hzFYCx8rJ6Mw

	cached_auth_request = {}
	current_auth_token = None
	yt_service = None

	def __init__(self):
		print("[MyTube] MyTubePlayerService - init")
		self.feedentries = []
		self.feed = None

	def startService(self):
		print("[MyTube] MyTubePlayerService - startService")

		self.yt_service = gdata.youtube.service.YouTubeService()

		# missing ssl support? youtube will help us on some feed urls
		self.yt_service.ssl = self.supportsSSL()

		# dont use it on class init; error on post and auth
		self.yt_service.developer_key = 'AI39si4AjyvU8GoJGncYzmqMCwelUnqjEMWTFCcUtK-VUzvWygvwPO-sadNwW5tNj9DDCHju3nnJEPvFy4WZZ6hzFYCx8rJ6Mw'
		self.yt_service.client_id = 'ytapi-dream-MyTubePlayer-i0kqrebg-0'

		# yt_service is reinit on every feed build; cache here to not reauth. remove init every time?
		if self.current_auth_token is not None:
			print("[MyTube] MyTubePlayerService - auth_cached")
			self.yt_service.SetClientLoginToken(self.current_auth_token)

#		self.loggedIn = False
		#os.environ['http_proxy'] = 'http://169.229.50.12:3128'
		#proxy = os.environ.get('http_proxy')
		#print "FOUND ENV PROXY-->",proxy
		#for a in os.environ.keys():
		#	print a

	def stopService(self):
		print("[MyTube] MyTubePlayerService - stopService")
		del self.ytService

	def getLoginTokenOnCurl(self, email, pw):

		opts = {
		  'service': 'youtube',
		  'accountType': 'HOSTED_OR_GOOGLE',
		  'Email': email,
		  'Passwd': pw,
		  'source': self.yt_service.client_id,
		}

		print("[MyTube] MyTubePlayerService - Starting external curl auth request")
		result = os.popen('curl -s -k -X POST "%s" -d "%s"' % (gdata.youtube.service.YOUTUBE_CLIENTLOGIN_AUTHENTICATION_URL, urlencode(opts))).read()

		return result

	def supportsSSL(self):
		return 'HTTPSConnection' in dir(httplib)

	def getFormattedTokenRequest(self, email, pw):
		return dict(parse_qsl(self.getLoginTokenOnCurl(email, pw).strip().replace('\n', '&')))

	def getAuthedUsername(self):
		# on external curl we can get real username
		if self.cached_auth_request.get('YouTubeUser') is not None:
			return self.cached_auth_request.get('YouTubeUser')

		if self.is_auth() is False:
			return ''

		# current gdata auth class save doesnt save realuser
		return 'Logged In'

	def auth_user(self, username, password):
		print("[MyTube] MyTubePlayerService - auth_use - " + str(username))

		if self.yt_service is None:
			self.startService()

		if self.current_auth_token is not None:
			print("[MyTube] MyTubePlayerService - auth_cached")
			self.yt_service.SetClientLoginToken(self.current_auth_token)
			return

		if self.supportsSSL() is False:
			print("[MyTube] MyTubePlayerService - HTTPSConnection not found trying external curl")
			self.cached_auth_request = self.getFormattedTokenRequest(username, password)
			if self.cached_auth_request.get('Auth') is None:
				raise Exception('Got no auth token from curl; you need curl and valid youtube login data')

			self.yt_service.SetClientLoginToken(self.cached_auth_request.get('Auth'))
		else:
			print("[MyTube] MyTubePlayerService - Using regularly ProgrammaticLogin for login")
			self.yt_service.email = username
			self.yt_service.password = password
			self.yt_service.ProgrammaticLogin()

		# double check login: reset any token on wrong logins
		if self.is_auth() is False:
			print("[MyTube] MyTubePlayerService - auth_use - auth not possible resetting")
			self.resetAuthState()
			return

		print("[MyTube] MyTubePlayerService - Got successful login")
		self.current_auth_token = self.auth_token()

	def resetAuthState(self):
		print("[MyTube] MyTubePlayerService - resetting auth")
		self.cached_auth_request = {}
		self.current_auth_token = None

		if self.yt_service is None:
			return

		self.yt_service.current_token = None
		self.yt_service.token_store.remove_all_tokens()

	def is_auth(self):
		if self.current_auth_token is not None:
			return True

		if self.yt_service.current_token is None:
			return False

		return self.yt_service.current_token.get_token_string() != 'None'

	def auth_token(self):
		return self.yt_service.current_token.get_token_string()

	def getFeedService(self, feedname):
		if feedname == "top_rated":
			return self.yt_service.GetTopRatedVideoFeed
		elif feedname == "most_viewed":
			return self.yt_service.GetMostViewedVideoFeed
		elif feedname == "recently_featured":
			return self.yt_service.GetRecentlyFeaturedVideoFeed
		elif feedname == "top_favorites":
			return self.yt_service.GetTopFavoritesVideoFeed
		elif feedname == "most_recent":
			return self.yt_service.GetMostRecentVideoFeed
		elif feedname == "most_discussed":
			return self.yt_service.GetMostDiscussedVideoFeed
		elif feedname == "most_linked":
			return self.yt_service.GetMostLinkedVideoFeed
		elif feedname == "most_responded":
			return self.yt_service.GetMostRespondedVideoFeed
		return self.yt_service.GetYouTubeVideoFeed

	def getFeed(self, url, feedname="", callback=None, errorback=None):
		print("[MyTube] MyTubePlayerService - getFeed:", url, feedname)
		self.feedentries = []
		ytservice = self.yt_service.GetYouTubeVideoFeed

		if feedname == "my_subscriptions":
			url = "http://gdata.youtube.com/feeds/api/users/default/newsubscriptionvideos"
		elif feedname == "my_favorites":
			url = "http://gdata.youtube.com/feeds/api/users/default/favorites"
		elif feedname == "my_history":
			url = "http://gdata.youtube.com/feeds/api/users/default/watch_history?v=2"
		elif feedname == "my_recommendations":
			url = "http://gdata.youtube.com/feeds/api/users/default/recommendations?v=2"
		elif feedname == "my_watch_later":
			url = "http://gdata.youtube.com/feeds/api/users/default/watch_later?v=2"
		elif feedname == "my_uploads":
			url = "http://gdata.youtube.com/feeds/api/users/default/uploads"
		elif feedname in ("hd", "most_popular", "most_shared", "on_the_web"):
			if feedname == "hd":
				url = "http://gdata.youtube.com/feeds/api/videos/-/HD"
			else:
				url = url + feedname
		elif feedname in ("top_rated", "most_viewed", "recently_featured", "top_favorites", "most_recent", "most_discussed", "most_linked", "most_responded"):
			url = None
			ytservice = self.getFeedService(feedname)

		queryThread = YoutubeQueryThread(ytservice, url, self.gotFeed, self.gotFeedError, callback, errorback)
		queryThread.start()
		return queryThread

	def search(self, searchTerms, startIndex=1, maxResults=25,
					orderby="relevance", time='all_time', racy="include",
					author="", lr="", categories="", sortOrder="ascending",
					callback=None, errorback=None):
		print("[MyTube] MyTubePlayerService - search()")
		self.feedentries = []
		query = gdata.youtube.service.YouTubeVideoQuery()
		query.vq = searchTerms
		query.orderby = orderby
		query.time = time
		query.racy = racy
		query.sortorder = sortOrder
		if lr is not None:
			query.lr = lr
		if categories[0] is not None:
			query.categories = categories
		query.start_index = startIndex
		query.max_results = maxResults
		queryThread = YoutubeQueryThread(self.yt_service.YouTubeQuery, query, self.gotFeed, self.gotFeedError, callback, errorback)
		queryThread.start()
		return queryThread

	def gotFeed(self, feed, callback):
		if feed is not None:
			self.feed = feed
			for entry in self.feed.entry:
				MyFeedEntry = MyTubeFeedEntry(self, entry)
				self.feedentries.append(MyFeedEntry)
		if callback is not None:
			callback(self.feed)

	def gotFeedError(self, exception, errorback):
		if errorback is not None:
			errorback(exception)

	def SubscribeToUser(self, username):
		try:
			new_subscription = self.yt_service.AddSubscriptionToChannel(username_to_subscribe_to=username)

			if isinstance(new_subscription, gdata.youtube.YouTubeSubscriptionEntry):
				print('[MyTube] MyTubePlayerService: New subscription added')
				return _('New subscription added')

			return _('Unknown error')
		except gdata.service.RequestError as req:
			return str('Error: ' + str(req[0]["body"]))
		except Exception as e:
			return str('Error: ' + e)

	def addToFavorites(self, video_id):
		try:
			video_entry = self.yt_service.GetYouTubeVideoEntry(video_id=video_id)
			response = self.yt_service.AddVideoEntryToFavorites(video_entry)

			# The response, if succesfully posted is a YouTubeVideoEntry
			if isinstance(response, gdata.youtube.YouTubeVideoEntry):
				print('[MyTube] MyTubePlayerService: Video successfully added to favorites')
				return _('Video successfully added to favorites')

			return _('Unknown error')
		except gdata.service.RequestError as req:
			return str('Error: ' + str(req[0]["body"]))
		except Exception as e:
			return str('Error: ' + e)

	def getTitle(self):
		return self.feed.title.text

	def getEntries(self):
		return self.feedentries

	def itemCount(self):
		return self.feed.items_per_page.text

	def getTotalResults(self):
		if self.feed.total_results is None:
			return 0

		return self.feed.total_results.text

	def getNextFeedEntriesURL(self):
		for link in self.feed.link:
			if link.rel == "next":
				return link.href
		return None

	def getCurrentPage(self):
		if self.feed.start_index is None:
			return 1

		return int(int(self.feed.start_index.text) / int(self.itemCount())) + 1


class YoutubeQueryThread(Thread):
	def __init__(self, query, param, gotFeed, gotFeedError, callback, errorback):
		Thread.__init__(self)
		self.messagePump = ePythonMessagePump()
		self.messages = ThreadQueue()
		self.gotFeed = gotFeed
		self.gotFeedError = gotFeedError
		self.callback = callback
		self.errorback = errorback
		self.query = query
		self.param = param
		self.canceled = False
		self.messagePump.recv_msg.get().append(self.finished)

	def cancel(self):
		self.canceled = True

	def run(self):
		try:
			if self.param is None:
				feed = self.query()
			else:
				feed = self.query(self.param)
			self.messages.push((True, feed, self.callback))
			self.messagePump.send(0)
		except Exception as ex:
			self.messages.push((False, ex, self.errorback))
			self.messagePump.send(0)

	def finished(self, val):
		if not self.canceled:
			message = self.messages.pop()
			if message[0]:
				self.gotFeed(message[1], message[2])
			else:
				self.gotFeedError(message[1], message[2])


myTubeService = MyTubePlayerService()
