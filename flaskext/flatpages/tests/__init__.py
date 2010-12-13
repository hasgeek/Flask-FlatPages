# coding: utf8

from __future__ import with_statement

import unittest
import tempfile
import shutil
import os.path
import datetime
from contextlib import contextmanager

import jinja2
from werkzeug.exceptions import NotFound
from flask import Flask
from flaskext.flatpages import FlatPages


@contextmanager
def temp_directory():
    """This context manager gives the path to a new temporary directory that
    is deleted (with all it's content) at the end of the with block.
    """
    directory = tempfile.mkdtemp()
    yield directory
    shutil.rmtree(directory)


@contextmanager
def temp_pages():
    """This context manager gives a FlatPages object configured
    in a temporary directory with a copy of the test pages.
    
    Using a temporary copy allows us to safely write and remove stuff without
    worrying about undoing our changes.
    """
    with temp_directory() as temp:
        source = os.path.join(os.path.dirname(__file__), 'pages')
        # Remove the destination dir as copytree wants it not to exist.
        # Doing so kind of defeats the purpose of tempfile as it introduces
        # a race condition, but should be good enough for our purpose.
        os.rmdir(temp)
        shutil.copytree(source, temp)
        app = Flask(__name__)
        app.config['FLATPAGES_ROOT'] = temp
        yield FlatPages(app)


class TestTempDirectory(unittest.TestCase):
    def test_removed(self):
        with temp_directory() as temp:
            assert os.path.isdir(temp)
        # should be removed now
        assert not os.path.exists(temp)
            
    def test_writing(self):
        with temp_directory() as temp:
            filename = os.path.join(temp, 'foo')
            with open(filename, 'w') as fd:
                fd.write('foo')
            assert os.path.isfile(filename)
        # should be removed now
        assert not os.path.exists(temp)
        assert not os.path.exists(filename)


class TestFlatPages(unittest.TestCase):
    def test_iter(self):
        pages = FlatPages(Flask(__name__))
        self.assertEquals(
            set(page.path for page in pages),
            set(['foo', 'foo/bar', 'foo/lorem/ipsum', 'hello'])
        )

    def test_get(self):
        pages = FlatPages(Flask(__name__))
        self.assertEquals(pages.get('foo/bar').path, 'foo/bar')
        self.assertEquals(pages.get('nonexistent'), None)
        self.assertEquals(pages.get('nonexistent', 42), 42)

    def test_get_or_404(self):
        pages = FlatPages(Flask(__name__))
        self.assertEquals(pages.get_or_404('foo/bar').path, 'foo/bar')
        self.assertRaises(NotFound, pages.get_or_404, 'nonexistent')

    def test_consistency(self):
        pages = FlatPages(Flask(__name__))
        for page in pages:
            assert pages.get(page.path) is page

    def test_yaml_meta(self):
        pages = FlatPages(Flask(__name__))
        foo = pages.get('foo')
        self.assertEquals(foo.meta, {
            'title': 'Foo > bar',
            'created': datetime.date(2010, 12, 11),
            'versions': [3.14, 42]
        })
        self.assertEquals(foo['title'], 'Foo > bar')
        self.assertEquals(foo['created'], datetime.date(2010, 12, 11))
        self.assertEquals(foo['versions'], [3.14, 42])
        self.assertRaises(KeyError, lambda: foo['nonexistent'])

    def test_markdown(self):
        pages = FlatPages(Flask(__name__))
        foo = pages.get('foo')
        self.assertEquals(foo.source, 'Foo *bar*\n')
        self.assertEquals(foo.html, '<p>Foo <em>bar</em></p>')

    def _unicode(self, pages):
        hello = pages.get('hello')
        self.assertEquals(hello.meta, {'title': u'世界',
                                       'template': 'article.html'})
        self.assertEquals(hello['title'], u'世界')
        self.assertEquals(hello.source, u'Hello, *世界*!\n')
        # Markdow
        self.assertEquals(hello.html, u'<p>Hello, <em>世界</em>!</p>')

    def test_unicode(self):
        pages = FlatPages(Flask(__name__))
        self._unicode(pages)

    def test_other_encoding(self):
        app = Flask(__name__)
        app.config['FLATPAGES_ENCODING'] = 'shift_jis'
        app.config['FLATPAGES_ROOT'] = 'pages_shift_jis'
        pages = FlatPages(app)
        self._unicode(pages)

    def test_other_extension(self):
        app = Flask(__name__)
        app.config['FLATPAGES_EXTENSION'] = '.txt'
        pages = FlatPages(app)
        self.assertEquals(
            set(page.path for page in pages),
            set(['not_a_page', 'foo/42/not_a_page'])
        )

    def test_render(self):
        app = Flask(__name__)
        app.jinja_env.loader = jinja2.DictLoader({
            'flatpage.html': '<h1>{{ page.title }}</h1>\n{{ page }}',
            'article.html': '<article>{{ page }}</article>',
        })
        pages = FlatPages(app)
        with app.test_request_context(): # needed for templating
            self.assertEquals(
                pages.render('foo'),
                # The content is correctly escaped but not the HTML
                '<h1>Foo &gt; bar</h1>\n<p>Foo <em>bar</em></p>'
            )
            self.assertEquals(
                pages.render('hello'),
                u'<article><p>Hello, <em>世界</em>!</p></article>'
            )

    def test_lazy_loading(self):
        with temp_pages() as pages:
            bar = pages.get('foo/bar')
            # bar.html is normally empty
            self.assertEquals(bar.meta, {})
            self.assertEquals(bar.source, '')
            
        with temp_pages() as pages:
            filename = os.path.join(pages.root, 'foo', 'bar.html')
            # write as pages is already constructed
            with open(filename, 'a') as fd:
                fd.write('a: b\n\nc')
            bar = pages.get('foo/bar')
            # bar was just loaded from the disk
            self.assertEquals(bar.meta, {'a': 'b'})
            self.assertEquals(bar.source, 'c')

    def test_reloading(self):
        with temp_pages() as pages:
            bar = pages.get('foo/bar')
            # bar.html is normally empty
            self.assertEquals(bar.meta, {})
            self.assertEquals(bar.source, '')
            
            filename = os.path.join(pages.root, 'foo', 'bar.html')
            # rewrite already loaded page
            with open(filename, 'w') as fd:
                # The newline is a separator between the (empty) metadata
                # and the source 'first'
                fd.write('\nfirst rewrite')

            bar2 = pages.get('foo/bar')
            # the disk is not hit again until requested
            self.assertEquals(bar2.meta, {})
            self.assertEquals(bar2.source, '')
            self.assert_(bar2 is bar)
            
            # request reloading
            pages.reset()
            
            # write again
            with open(filename, 'w') as fd:
                fd.write('\nsecond rewrite')
            
            # get another page
            pages.get('hello')

            # write again
            with open(filename, 'w') as fd:
                fd.write('\nthird rewrite')

            # All pages are read at once when any is used
            bar3 = pages.get('foo/bar')
            self.assertEquals(bar3.meta, {})
            self.assertEquals(bar3.source, 'second rewrite') # not third
            # Page objects are not reused when a file is re-read.
            self.assert_(bar3 is not bar2)
            
            # Removing does not trigger reloading either
            os.remove(filename)

            bar4 = pages.get('foo/bar')
            self.assertEquals(bar4.meta, {})
            self.assertEquals(bar4.source, 'second rewrite')
            self.assert_(bar4 is bar3)
            
            pages.reset()

            bar5 = pages.get('foo/bar')
            self.assert_(bar5 is None)

    def test_caching(self):
        with temp_pages() as pages:
            foo = pages.get('foo')
            bar = pages.get('foo/bar')
            
            filename = os.path.join(pages.root, 'foo', 'bar.html')
            with open(filename, 'w') as fd:
                fd.write('\nrewriten')

            pages.reset()
            
            foo2 = pages.get('foo')
            bar2 = pages.get('foo/bar')

            # Page objects are cached and unmodified files (according to the
            # modification date) are not parsed again.
            self.assert_(foo2 is foo)
            self.assert_(bar2 is not bar)
            

if __name__ == '__main__':
    unittest.main()
