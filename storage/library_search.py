"""Library display search; LIKE compatibility plus separator-insensitive matching."""
from storage.database import execute


def find(db, lock, term, kind):
    like = '%' + term + '%'
    return execute(db, lock,
                   "select * from items where (title like ? or author like ? or topic like ? "
                   "or mh_search(title,?) or mh_search(author,?) or mh_search(topic,?)) "
                   "and (kind=? or ?='') order by id desc",
                   (like, like, like, term, term, term, kind, kind))
