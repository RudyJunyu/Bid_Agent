"""Enterprise asset lifecycle: create, attach versions, project link, usable filter."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.infrastructure.object_store import object_store
from bid_agent.repositories import assets, audit


def create_asset(user: Principal, **kwargs) -> dict:
    asset = assets.create_asset(user, **kwargs)
    audit.record(
        actor=user,
        action='asset.created',
        object_type='enterprise_asset',
        object_id=asset['id'],
        summary=f'创建企业资产：{asset["title"]}',
        detail={'category': asset['category'], 'status': asset['status']},
    )
    return asset


def update_asset(asset_id: str, user: Principal, **kwargs) -> dict:
    asset = assets.update_asset(asset_id, user, **kwargs)
    audit.record(
        actor=user,
        action='asset.updated',
        object_type='enterprise_asset',
        object_id=asset_id,
        summary=f'更新企业资产：{asset["title"]}',
        detail={'status': asset['status'], 'usable': asset['usable']},
    )
    return asset


def upload_version(asset_id: str, user: Principal, *, file_obj, filename: str, notes: str = '') -> dict:
    # Ensure asset exists before writing bytes.
    assets.get_asset(asset_id, user)
    stored = object_store.put(file_obj, filename or '')
    version = assets.add_version(asset_id, user, stored=stored, notes=notes)
    audit.record(
        actor=user,
        action='asset.version_added',
        object_type='enterprise_asset',
        object_id=asset_id,
        summary=f'上传资产附件 v{version["version"]}：{version["file_name"]}',
        detail={'version_id': version['id'], 'sha256': version['sha256']},
    )
    asset = assets.get_asset(asset_id, user)
    return {'asset': asset, 'version': version}


def link_asset(project_id: str, asset_id: str, user: Principal) -> dict:
    result = assets.link_to_project(project_id, asset_id, user)
    audit.record(
        actor=user,
        action='asset.linked',
        object_type='enterprise_asset',
        object_id=asset_id,
        summary='资产关联到项目',
        project_id=project_id,
        detail=result,
    )
    return result


def unlink_asset(project_id: str, asset_id: str, user: Principal) -> dict:
    result = assets.unlink_from_project(project_id, asset_id, user)
    audit.record(
        actor=user,
        action='asset.unlinked',
        object_type='enterprise_asset',
        object_id=asset_id,
        summary='取消资产与项目关联',
        project_id=project_id,
        detail=result,
    )
    return result


def list_usable_for_project(project_id: str, user: Principal) -> list[dict]:
    return assets.list_for_project(project_id, user, usable_only=True)


def match_assets_for_requirement(requirement: dict, candidate_assets: list[dict]) -> list[dict]:
    """Suggest usable assets for a requirement; expired candidates are never returned."""
    category = requirement.get('category')
    text = ' '.join(
        str(part or '')
        for part in (
            requirement.get('title'),
            requirement.get('normalized_value'),
            requirement.get('raw_text'),
        )
    )
    category_map = {
        'qualification': {'qualification', 'personnel'},
        'commercial': {'performance', 'financial', 'case'},
        'technical': {'case', 'template', 'other'},
        'rejection': set(),
        'scoring': {'case', 'template'},
    }
    allowed = category_map.get(category, set(assets.CATEGORIES))
    matches = []
    for asset in candidate_assets:
        if not asset.get('usable'):
            continue
        if allowed and asset.get('category') not in allowed:
            continue
        score = 0
        title = asset.get('title') or ''
        subject = asset.get('subject_name') or ''
        if title and title in text:
            score += 3
        if subject and subject in text:
            score += 2
        for tag in asset.get('tags') or []:
            if tag and str(tag) in text:
                score += 1
        if score or (allowed and asset.get('category') in allowed and category == 'qualification'):
            matches.append({**asset, 'match_score': score})
    matches.sort(key=lambda item: (-item.get('match_score', 0), item.get('title') or ''))
    return matches[:5]


def expired_linked_assets(project_id: str, user: Principal) -> list[dict]:
    linked = assets.list_for_project(project_id, user, usable_only=False)
    return [item for item in linked if item.get('status') == 'expired' or item.get('expired')]
