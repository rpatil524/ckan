# encoding: utf-8
from __future__ import annotations

from typing import Optional, Any

from sqlalchemy.orm import relationship, Mapped
from sqlalchemy import (types, Column, Table, ForeignKey, UniqueConstraint,
                        Index)
from typing_extensions import Self

import ckan  # this import is needed

import ckan.model
import ckan.model.core as core
import ckan.model.meta as meta
import ckan.model.types as _types
import ckan.model.domain_object as domain_object
import ckan.model.vocabulary as vocabulary

import ckan.logic
from ckan.types import Query

__all__ = ['tag_table', 'package_tag_table', 'Tag', 'PackageTag',
           'MAX_TAG_LENGTH', 'MIN_TAG_LENGTH']

MAX_TAG_LENGTH = 100
MIN_TAG_LENGTH = 2

tag_table = Table('tag', meta.metadata,
    Column('id', types.UnicodeText, primary_key=True, default=_types.make_uuid),
    Column('name', types.Unicode(MAX_TAG_LENGTH), nullable=False),
    Column('vocabulary_id',
        types.Unicode(vocabulary.VOCABULARY_NAME_MAX_LENGTH),
        ForeignKey('vocabulary.id')),
    UniqueConstraint('name', 'vocabulary_id'),
    Index('idx_tag_id', 'id'),
    Index('idx_tag_name', 'name'),
)

package_tag_table = Table('package_tag', meta.metadata,
    Column('id', types.UnicodeText, primary_key=True, default=_types.make_uuid),
    Column('package_id', types.UnicodeText, ForeignKey('package.id')),
    Column('tag_id', types.UnicodeText, ForeignKey('tag.id')),
    Column('state', types.UnicodeText, default=core.State.ACTIVE),
    Index('idx_package_tag_id', 'id'),
    Index('idx_package_tag_pkg_id', 'package_id'),
    Index('idx_package_tag_pkg_id_tag_id', 'tag_id', 'package_id'),
)


class Tag(domain_object.DomainObject):
    id: Mapped[str]
    name: Mapped[str]
    vocabulary_id: Mapped[Optional[str]]

    package_tags: Mapped[list['PackageTag']]
    vocabulary: Mapped[Optional['ckan.model.Vocabulary']]

    def __init__(self, name: str='', vocabulary_id: Optional[str]=None) -> None:
        self.name = name
        self.vocabulary_id = vocabulary_id

    # not stateful so same as purge
    def delete(self) -> None:
        self.purge()

    @classmethod
    def by_id(cls, tag_id: str, autoflush: bool=True) -> Optional[Self]:
        '''Return the tag with the given id, or None.

        :param tag_id: the id of the tag to return
        :type tag_id: string

        :returns: the tag with the given id, or None if there is no tag with
            that id
        :rtype: ckan.model.tag.Tag

        '''
        query = meta.Session.query(cls).filter(cls.id==tag_id)
        query = query.autoflush(autoflush)
        tag = query.first()
        return tag

    @classmethod
    def by_name(
            cls, name: Optional[str],
            autoflush: bool = True,
            for_update: bool = False,
            vocab: Optional['ckan.model.Vocabulary'] = None,
    ) -> Optional[Self]:
        '''Return the tag with the given name, or None.

        By default only free tags (tags which do not belong to any vocabulary)
        are returned.

        If the optional argument ``vocab`` is given then only tags from that
        vocabulary are returned, or ``None`` if there is no tag with that name
        in that vocabulary.

        :param name: the name of the tag to return
        :type name: string
        :param vocab: the vocabulary to look in (optional, default: None)
        :type vocab: ckan.model.vocabulary.Vocabulary

        :returns: the tag object with the given id or name, or None if there is
            no tag with that id or name
        :rtype: ckan.model.tag.Tag

        '''
        if vocab:
            query = meta.Session.query(cls).filter(cls.name==name).filter(
                cls.vocabulary_id==vocab.id)
        else:
            query = meta.Session.query(cls).filter(cls.name==name).filter(
                cls.vocabulary_id.is_(None))
        query = query.autoflush(autoflush)
        tag = query.first()
        return tag

    @classmethod
    def get(cls, tag_id_or_name: str,
            vocab_id_or_name: Optional[str]=None) -> Optional[Tag]:
        '''Return the tag with the given id or name, or None.

        By default only free tags (tags which do not belong to any vocabulary)
        are returned.

        If the optional argument ``vocab_id_or_name`` is given then only tags
        that belong to that vocabulary will be returned, and ``None`` will be
        returned if there is no vocabulary with that vocabulary id or name or
        if there is no tag with that tag id or name in that vocabulary.

        :param tag_id_or_name: the id or name of the tag to return
        :type tag_id_or_name: string
        :param vocab_id_or_name: the id or name of the vocabulary to look for
            the tag in
        :type vocab_id_or_name: string

        :returns: the tag object with the given id or name, or None if there is
            no tag with that id or name
        :rtype: ckan.model.tag.Tag

        '''
        vocab = None
        if vocab_id_or_name:
            vocab = vocabulary.Vocabulary.get(vocab_id_or_name)
            if vocab is None:
                # The user specified an invalid vocab.
                return None

        tag = Tag.by_id(tag_id_or_name)
        if not tag:
            return Tag.by_name(tag_id_or_name, vocab=vocab)
        elif vocab and tag.vocabulary_id != vocab.id:
                return None
        return tag

    @classmethod
    def all(cls, vocab_id_or_name: Optional[str]=None) -> Query[Self]:
        '''Return all tags that are currently applied to any dataset.

        By default only free tags (tags which do not belong to any vocabulary)
        are returned. If the optional argument ``vocab_id_or_name`` is given
        then only tags from that vocabulary are returned.

        :param vocab_id_or_name: the id or name of the vocabulary to look in
            (optional, default: None)
        :type vocab_id_or_name: string

        :returns: a list of all tags that are currently applied to any dataset
        :rtype: list of ckan.model.tag.Tag objects

        '''
        if vocab_id_or_name:
            vocab = vocabulary.Vocabulary.get(vocab_id_or_name)
            if vocab is None:
                # The user specified an invalid vocab.
                raise ckan.logic.NotFound("could not find vocabulary '%s'"
                        % vocab_id_or_name)
            query = meta.Session.query(cls).filter(cls.vocabulary_id==vocab.id)
        else:
            subquery = meta.Session.query(PackageTag).\
                filter(PackageTag.state == 'active').subquery()

            query = meta.Session.query(cls).\
                filter(cls.vocabulary_id.is_(None)).\
                distinct().\
                join(subquery, cls.id==subquery.c.tag_id)

        return query

    @property
    def packages(self) -> list['ckan.model.Package']:
        '''Return a list of all packages that have this tag, sorted by name.

        :rtype: list of ckan.model.package.Package objects

        '''
        q: 'Query[ckan.model.Package]' = meta.Session.query(ckan.model.Package)
        q: 'Query[ckan.model.Package]' = q.join(PackageTag)
        q = q.filter(ckan.model.PackageTag.tag_id == self.id)
        q = q.filter(ckan.model.Package.state=='active')
        q = q.order_by(ckan.model.Package.name)
        packages = q.all()
        return packages

    def __repr__(self) -> str:
        return '<Tag %s>' % self.name

class PackageTag(core.StatefulObjectMixin,
                 domain_object.DomainObject):
    id: Mapped[str]
    package_id: Mapped[str]
    tag_id: Mapped[str]
    state: Mapped[Optional[str]]

    pkg: Mapped[Optional['ckan.model.Package']]
    package: Mapped[Optional['ckan.model.Package']]
    tag: Mapped[Optional[Tag]]

    def __init__(
            self, package: Optional['ckan.model.Package'] = None,
            tag: Optional[Tag] = None, state: Optional[str] = None,
            **kwargs: Any) -> None:
        self.package = package
        self.tag = tag
        self.state = state
        for k,v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        assert self.package
        assert self.tag
        return u'<PackageTag package=%s tag=%s>' % (self.package.name, self.tag.name)

    def related_packages(self) -> list['ckan.model.Package']:
        if self.package:
            return [self.package]
        return []

meta.registry.map_imperatively(Tag, tag_table, properties={
    'package_tags': relationship(PackageTag, backref='tag',
                                 cascade='all, delete, delete-orphan',
                                 cascade_backrefs=False,
        ),
    'vocabulary': relationship(vocabulary.Vocabulary,
                           order_by=tag_table.c["name"])
    })

# NB meta.mapper(tag.PackageTag... is found in package.py, because if it was
# here it we'd get circular references
