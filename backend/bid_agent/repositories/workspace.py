"""Project memberships and immutable file versions."""
from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import ConflictError, ForbiddenError, NotFoundError, new_id, now, transaction


def check_access(conn, project_id: str, user: Principal, *, write=False, owner=False) -> None:
    if not conn.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
        raise NotFoundError('项目不存在')
    if user.is_admin:
        return
    membership = conn.execute('SELECT role FROM project_members WHERE project_id=? AND user_id=?',
                              (project_id, user.id)).fetchone()
    if not membership:
        # Do not reveal whether an inaccessible project exists.
        raise NotFoundError('项目不存在')
    if (write and membership['role'] == 'viewer') or (owner and membership['role'] != 'owner'):
        raise ForbiddenError('没有此操作权限')


def create_project(title: str, user: Principal) -> dict:
    project_id, timestamp = new_id('prj'), now()
    with transaction(immediate=True) as conn:
        conn.execute('INSERT INTO projects(id,project_name,status,created_at,updated_at) VALUES(?,?,?,?,?)',
                     (project_id, title, '待解析', timestamp, timestamp))
        conn.execute('INSERT INTO project_members VALUES(?,?,?)', (project_id, user.id, 'owner'))
        return dict(conn.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone())


def list_projects(user: Principal) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute('''SELECT p.*, (SELECT role FROM project_members m WHERE m.project_id=p.id AND m.user_id=?) AS access_role,
            (SELECT count(*) FROM documents d WHERE d.project_id=p.id) AS document_count
            FROM projects p WHERE ? OR EXISTS(SELECT 1 FROM project_members m WHERE m.project_id=p.id AND m.user_id=?)
            ORDER BY p.created_at DESC''', (user.id, user.is_admin, user.id)).fetchall()
        return [dict(row) for row in rows]


def add_member(project_id: str, username: str, role: str, actor: Principal) -> None:
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, actor, owner=True)
        user = conn.execute("SELECT id FROM users WHERE username=? AND id!='local'", (username,)).fetchone()
        if not user:
            raise NotFoundError('用户不存在')
        existing = conn.execute('SELECT role FROM project_members WHERE project_id=? AND user_id=?',
                                (project_id, user['id'])).fetchone()
        if existing and existing['role'] == 'owner':
            raise ConflictError('不能通过成员接口修改项目所有者')
        conn.execute('''INSERT INTO project_members VALUES(?,?,?) ON CONFLICT(project_id,user_id)
            DO UPDATE SET role=excluded.role''', (project_id, user['id'], role))


def save_version(project_id: str, user: Principal, file: dict, *, document_id=None,
                 title: str = '', kind: str = 'tender', parent_document_id=None) -> tuple[dict, bool]:
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        if parent_document_id:
            parent = conn.execute('SELECT id FROM documents WHERE id=? AND project_id=?',
                                  (parent_document_id, project_id)).fetchone()
            if not parent:
                raise NotFoundError('关联原文档不属于当前项目')
        if document_id:
            document = conn.execute('SELECT * FROM documents WHERE id=? AND project_id=?',
                                    (document_id, project_id)).fetchone()
            if not document:
                raise NotFoundError('文档不存在')
            existing = conn.execute('SELECT * FROM document_versions WHERE document_id=? AND sha256=?',
                                    (document_id, file['sha256'])).fetchone()
            if existing:
                return dict(existing), False
        else:
            document_id = new_id('doc')
            conn.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',
                         (document_id, project_id, title or file['file_name'], kind, parent_document_id, now()))
        version_number = conn.execute('SELECT coalesce(max(version),0)+1 FROM document_versions WHERE document_id=?',
                                      (document_id,)).fetchone()[0]
        version_id = new_id('dv')
        conn.execute('''INSERT INTO document_versions
            (id,document_id,version,file_name,media_type,object_key,sha256,size_bytes,created_by,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''', (version_id, document_id, version_number, file['file_name'],
            file['media_type'], file['object_key'], file['sha256'], file['size_bytes'], user.id, now()))
        return dict(conn.execute('SELECT * FROM document_versions WHERE id=?', (version_id,)).fetchone()), True


def list_documents(project_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        documents = [dict(row) for row in conn.execute('SELECT * FROM documents WHERE project_id=? ORDER BY created_at DESC',
                                                       (project_id,))]
        for document in documents:
            document['versions'] = [dict(row) for row in conn.execute('''SELECT id,document_id,version,file_name,
                media_type,sha256,size_bytes,created_by,created_at FROM document_versions
                WHERE document_id=? ORDER BY version DESC''', (document['id'],))]
        return documents


def get_version(version_id: str, user: Principal, *, write=False) -> dict:
    with transaction() as conn:
        row = conn.execute('''SELECT v.*,d.project_id FROM document_versions v
            JOIN documents d ON d.id=v.document_id WHERE v.id=?''', (version_id,)).fetchone()
        if not row:
            raise NotFoundError('文档版本不存在')
        check_access(conn, row['project_id'], user, write=write)
        return dict(row)
