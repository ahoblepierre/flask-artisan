import pytest
from sqlalchemy import inspect as sa_inspect

from flask_artisan import DB
from flask_artisan.database import (
    Mapped,
    Model,
    SoftDeletes,
    belongs_to,
    belongs_to_many,
    foreign_id,
    has_many,
    has_one,
)


class RUser(Model):
    name: Mapped[str]
    posts = has_many("RPost")
    profile = has_one("RProfile")


class RProfile(Model):
    bio: Mapped[str]
    r_user_id: Mapped[int] = foreign_id("r_users")


class RPost(Model, SoftDeletes):
    title: Mapped[str]
    r_user_id: Mapped[int] = foreign_id("r_users")
    author_id: Mapped[int | None] = foreign_id("r_users")
    r_user = belongs_to("RUser")
    author = belongs_to("RUser")
    tags = belongs_to_many("RTag")
    comments = has_many("RComment")


class RTag(Model):
    name: Mapped[str]


class RComment(Model):
    body: Mapped[str]
    r_post_id: Mapped[int] = foreign_id("r_posts", on_delete="CASCADE")


class RArticle(Model):
    labels = belongs_to_many("RTag", table="taggings")


@pytest.fixture
def data(db_app):
    db_app()
    ana = RUser.create(name="ana")
    bob = RUser.create(name="bob")
    RProfile.create(bio="hi", r_user_id=ana.id)
    first = RPost.create(title="first", r_user_id=ana.id, author_id=bob.id)
    RPost.create(title="second", r_user_id=ana.id)
    RComment.create(body="c1", r_post_id=first.id)
    RPost.create(title="gone", r_user_id=ana.id).delete()
    DB.remove()
    return ana.id, bob.id


def test_has_many_and_belongs_to(data):
    ana = RUser.find(data[0])
    assert sorted(p.title for p in ana.posts) == ["first", "second"]
    assert RPost.where("title", "first").first().r_user.name == "ana"


def test_belongs_to_key_from_attribute(data):
    post = RPost.where("title", "first").first()
    assert post.author.name == "bob" and post.r_user.name == "ana"


def test_has_one_returns_object(data):
    assert RUser.find(data[0]).profile.bio == "hi"
    assert RUser.find(data[1]).profile is None


def test_belongs_to_many_pivot(data):
    assert "r_post_r_tag" in Model.metadata.tables
    post = RPost.where("title", "first").first()
    post.tags.append(RTag.create(name="py"))
    post.save()
    DB.remove()
    assert [t.name for t in RPost.where("title", "first").first().tags] == ["py"]


def test_belongs_to_many_custom_table(data):
    assert "taggings" in Model.metadata.tables


def test_with_loads_eagerly(data):
    users = RUser.with_("posts").where("name", "ana").get()
    DB.remove()
    assert sorted(p.title for p in users[0].posts) == ["first", "second"]


def test_with_nested(data):
    user = RUser.with_("posts.comments").where("name", "ana").first()
    DB.remove()
    first = next(p for p in user.posts if p.title == "first")
    assert [c.body for c in first.comments] == ["c1"]


def test_with_unknown_relation_raises(data):
    with pytest.raises(ValueError, match="nope"):
        RUser.with_("nope").get()


def test_relation_excludes_trashed(data):
    assert "gone" not in [p.title for p in RUser.find(data[0]).posts]
    eager = RUser.with_("posts").where("name", "ana").first()
    assert "gone" not in [p.title for p in eager.posts]


def test_to_dict_includes_loaded_relations_only(data):
    eager = RUser.with_("posts").where("name", "ana").first().to_dict()
    assert sorted(p["title"] for p in eager["posts"]) == ["first", "second"]
    DB.remove()
    lazy = RUser.find(data[0])
    assert "posts" not in lazy.to_dict()
    assert "posts" in sa_inspect(lazy).unloaded


def test_inverse_relations_linked_without_warning(data, recwarn):
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
    assert not [w for w in recwarn if "conflicts with relationship" in str(w.message)]
    ana = RUser.find(data[0])
    assert len(ana.posts) == 2  # collection chargée
    post = RPost(title="new")
    post.r_user = ana
    assert post in ana.posts  # synchronisé par back_populates
