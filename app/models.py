from flask_login import UserMixin, AnonymousUserMixin
from datetime import datetime
from . import db, login_manager, users_upload, manga_upload, news_upload
from flask import current_app
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from werkzeug.security import generate_password_hash, check_password_hash
from flask import url_for

class Permission:
    FOLLOW = 1
    COMMENT = 2
    PUBLICATION = 4
    MODERATE = 8
    ADMIN = 16
    BANNED = 32
    PREMIUM = 64


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    default = db.Column(db.Boolean, default=False, index=True)
    permissions = db.Column(db.Integer)
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __init__(self, **kwargs):
        super(Role, self).__init__(**kwargs)
        if self.permissions is None:
            self.permissions = 0

    @staticmethod
    def insert_roles():
        roles = {
            'Administrator': [Permission.FOLLOW, Permission.COMMENT,
                              Permission.PUBLICATION, Permission.MODERATE,
                              Permission.ADMIN],
            'Moderator': [Permission.FOLLOW, Permission.COMMENT,
                          Permission.PUBLICATION, Permission.MODERATE],
            'Premium': [Permission.PREMIUM, Permission.FOLLOW, Permission.COMMENT],
            'User': [Permission.FOLLOW, Permission.COMMENT],
            'Banned': [Permission.BANNED]
        }
        default_role = 'User'
        for r in roles:
            role = Role.query.filter_by(name=r).first()
            if role is None:
                role = Role(name=r)
            role.reset_permissions()
            for perm in roles[r]:
                role.add_permission(perm)
            role.default = (role.name == default_role)
            db.session.add(role)
        db.session.commit()

    def add_permission(self, perm):
        if not self.has_permission(perm):
            self.permissions += perm

    def reset_permissions(self):
        self.permissions = 0

    def has_permission(self, perm):
        return self.permissions & perm == perm

    def __repr__(self):
        return 'Role %r' % self.name

follows = db.Table('follows',
                    db.Column('follower_id', db.Integer, db.ForeignKey('users.id')),
                    db.Column('followed_id', db.Integer, db.ForeignKey('users.id')),
                    db.Column('timestamp', db.DateTime, default=datetime.utcnow())
                    )

logs = db.Table('logs',
                    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
                    db.Column('manga_id', db.Integer, db.ForeignKey('manga.id')),
                    db.Column('timestamp', db.DateTime, default=datetime.utcnow())
                    )


class Ban(db.Model):
    __tablename__ = 'bans'
    id = db.Column(db.Integer, primary_key=True)
    created_time = db.Column(db.DateTime, default=datetime.utcnow)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    last_role = db.Column(db.String(16))
    reason = db.Column(db.String(2048))

    def __repr__(self):
        return u'Bans: %r, ' % self.user_id


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(64), unique=True, index=True)
    username = db.Column(db.String(64), unique=True, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    password_hash = db.Column(db.String(128))
    confirmed = db.Column(db.Boolean, default=False)
    name = db.Column(db.String(64))
    location = db.Column(db.String(64))
    site = db.Column(db.String(64))
    about_me = db.Column(db.Text())
    member_since = db.Column(db.DateTime(), default=datetime.utcnow)
    last_seen = db.Column(db.DateTime(), default=datetime.utcnow)
    avatar = db.Column(db.String(128))
    background = db.Column(db.String(128))
    manga_user = db.relationship('Manga', backref='user', lazy='dynamic')
    chapter = db.relationship('Chapter', backref='user', lazy='dynamic')
    followers = db.relationship('User',
                    secondary=follows,
                    primaryjoin=follows.c.followed_id==id,
                    secondaryjoin=follows.c.follower_id==id,
                    backref=db.backref('followed', lazy='dynamic'),
                    lazy='dynamic')

    comments = db.relationship('Comment', backref='user', lazy='dynamic')
    news = db.relationship('News', backref='user', lazy='dynamic')
    bans = db.relationship('Ban', foreign_keys='Ban.user_id', lazy='dynamic')

    def __init__(self, **kwargs):
        super(User, self).__init__(**kwargs)
        if self.role is None:
            if self.email == current_app.config['MANGA_ADMIN']:
                self.role = Role.query.filter_by(name='Administrator').first()
            if self.role is None:
                self.role = Role.query.filter_by(default=True).first()

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = generate_password_hash(password)

    def verify_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar_url(self, _external=False):
        if self.avatar:
            return users_upload.url(self.avatar)
        else:
            return url_for('static', filename='img/avatar.jpg', _external=_external)

    def background_url(self, _external=False):
        if self.background:
            return users_upload.url(self.background)
        else:
            return url_for('static', filename='img/background.png', _external=_external)

    def generate_confirmation_token(self, expiration=3600):
            s = Serializer(current_app.config['SECRET_KEY'], expiration)
            return s.dumps({'confirm': self.id}).decode('utf-8')

    def confirm(self, token):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token.encode('utf-8'))
        except:
            return False
        if data.get('confirm') != self.id:
            return False
        self.confirmed = True
        db.session.add(self)
        return True

    def generate_reset_token(self, expiration=3600):
        s = Serializer(current_app.config['SECRET_KEY'], expiration)
        return s.dumps({'reset': self.id}).decode('utf-8')

    @staticmethod
    def reset_password(token, new_password):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token.encode('utf-8'))
        except:
            return False
        user = User.query.get(data.get('reset'))
        if user is None:
            return False
        user.password = new_password
        db.session.add(user)
        return True

    def generate_email_change_token(self, new_email, expiration=3600):
        s = Serializer(current_app.config['SECRET_KEY'], expiration)
        return s.dumps(
            {'change_email': self.id, 'new_email': new_email}).decode('utf-8')

    def change_email(self, token):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token.encode('utf-8'))
        except:
            return False
        if data.get('change_email') != self.id:
            return False
        new_email = data.get('new_email')
        if new_email is None:
            return False
        if self.query.filter_by(email=new_email).first() is not None:
            return False
        self.email = new_email
        db.session.add(self)
        return True

    def can(self, perm):
        return self.role is not None and self.role.has_permission(perm)

    @property
    def is_administrator(self):
        return self.can(Permission.ADMIN)

    @property
    def banned(self):
        return self.can(Permission.BANNED)

    def ping(self):
        self.last_seen = datetime.utcnow()
        db.session.add(self)
        db.session.commit()

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)
            db.session.add(self) 

    def unfollow(self, user):
        f = self.followed.filter_by(id=user.id).first()
        if f:
            self.followed.remove(f)
            db.session.add(self)

    def is_following(self, user):
        if user.id is None:
            return False
        return self.followed.filter_by(
            id=user.id).first() is not None

    def read(self, manga):
        if not self.is_reading(manga):
            self.manga.append(manga)
            db.session.add(self)

    def unread(self, manga):
        f = self.manga.filter_by(id=manga.id).first()
        if f:
            self.manga.remove(f)
            db.session.add(self)

    def is_reading(self, manga):
        if manga.id is None:
            return False
        return self.manga.filter_by(
            id=manga.id).first() is not None

    def __repr__(self):
        return 'User %r' % self.id                


class Manga(db.Model):
    __tablename__ = 'manga'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), unique=True, index=True)
    author = db.Column(db.String(128))
    image = db.Column(db.String(128))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    catalog = db.deferred(db.Column(db.Text, default=""))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    chapter = db.relationship('Chapter', backref='manga', lazy='dynamic')
    comments = db.relationship('Comment', backref='manga', lazy='dynamic')
    users = db.relationship('User',
                        secondary=logs,
                        backref=db.backref('manga', lazy='dynamic'),
                        lazy='dynamic')

    @property
    def tags_string(self):
        return ",".join([tag.name for tag in self.tags.all()])

    @tags_string.setter
    def tags_string(self, value):
        self.tags = []
        tags_list = [tag.strip() for tag in value.split(',') if len(tag.strip()) > 0]
        if len(tags_list) > 0:
            for str in tags_list:
                tag = Tag.query.filter(Tag.name.ilike(str)).first()
                if tag is None:
                    tag = Tag(name=str)
                self.tags.append(tag)
            db.session.add(self)
            db.session.commit()

    def image_url(self, _external=False):
        if self.image:
            return manga_upload.url(self.image)
        else:
            return url_for('static', filename='img/manga.jpg', _external=_external)

    def __repr__(self):
        return u'Manga: %r ' % self.title


class Chapter(db.Model):
    __tablename__ = 'chapters'
    id = db.Column(db.Integer, primary_key=True)
    volume = db.Column(db.Integer)
    chapter = db.Column(db.Integer)
    title = db.Column(db.String(128))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    manga_id = db.Column(db.Integer, db.ForeignKey('manga.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    image = db.relationship('Images', backref='chapter', lazy='dynamic')

    def image_url(self):
        if self.image:
            url = []
            for m in self.image.all():
                url.append(manga_upload.url(m.url))
            return url

    def __repr__(self):
        return 'Title: %r' % self.chapter


manga_tag = db.Table('manga_tags',
                    db.Column('manga_id', db.Integer, db.ForeignKey('manga.id')),
                    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id'))
                    )


class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32))
    manga = db.relationship('Manga',
                            secondary=manga_tag,
                            backref=db.backref('tags', lazy='dynamic'),
                            lazy='dynamic')
    
    @staticmethod
    def insert_tags():
        names = [
            "Сёнен", "Сёнен-ай", "Сэйнэн", "Сёдзе", "Сёдзе-ай", "Дзёсей", "Комедия", "Романтика", "Школа",
            "Безумие", "Боевые искусства", "Вампиры", "Военное", "Гарем", "Гурман", "Демоны", "Детектив",
            "Детское", "Драма", "Игры", "Исторический", "Космос", "Магия", "Машины", "Меха", "Музыка", "Пародия",
            "Повседневность", "Полиция", "Приключения", "Психологическое", "Работа", "Самураи", "Сверхъестественное",
            "Смена пола", "Спорт", "Супер сила", "Ужасы", "Фантастика", "Фэнтези", "Экшен", "Этти", "Триллер", "Эротика",
            "Хентай", "Яой", "Юри", "Додзинси"
        ]
        
        for name in names:
            search = Tag.query.filter(Tag.name.ilike(name)).first()
            if search is None:
                tag = Tag(name=name)
                db.session.add(tag)
        db.session.commit()
        

    def __repr__(self):
        return u'Tag: %r' % self.id


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    disabled = db.Column(db.Boolean)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    manga_id = db.Column(db.Integer, db.ForeignKey('manga.id'))
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'))

    def __repr__(self):
        return 'Body: %r ' % self.body


class News(db.Model):
    __tablename__ = 'news'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128))
    body = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    comments = db.relationship('Comment', backref='news', lazy='dynamic')
    image = db.relationship('Images', backref='news', lazy='dynamic')

    def get_poster(self, _external=True):
        if self.image:
            return news_upload.url(self.image.first().url)
        else:
            return url_for('static', filename='img/news.png', _external=_external)
    
    def image_url(self):
        if self.image:
            url = []
            for m in self.image.all():
                url.append(news_upload.url(m.url))
            return url

    def __repr__(self):
        return 'Title: %r ' % self.title

class Images(db.Model):
    __tablename__ = 'images'
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(128))
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'))
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapters.id'))

    def image_url(self):
        if self.url:
            return manga_upload.url(self.url)

class AnonymousUser(AnonymousUserMixin):
    def can(self, permissions):
        return False

    @property
    def is_administrator(self):
        return False

    def is_reading(self, manga):
        return False

login_manager.anonymous_user = AnonymousUser


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))