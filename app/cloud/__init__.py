from app.cloud.github_provider import GitHubProvider
from app.cloud.gitlab_provider import GitLabProvider
from app.cloud.webdav_provider import WebDAVProvider
from app.cloud.local_folder_provider import LocalFolderProvider
from app.cloud.dropbox_provider import DropboxProvider

# Реестр доступных облачных провайдеров: тип -> (человекочитаемое имя, класс)
PROVIDER_REGISTRY = {
    'github': ('GitHub (репозиторий)', GitHubProvider),
    'gitlab': ('GitLab (репозиторий)', GitLabProvider),
    'webdav': ('WebDAV (Яндекс.Диск и др.)', WebDAVProvider),
    'dropbox': ('Dropbox', DropboxProvider),
    'local': ('Локальная синхронизируемая папка', LocalFolderProvider),
}


def create_provider(account):
    """Создаёт экземпляр провайдера по объекту CloudAccount.
    account.secret должен быть заполнен (токен/пароль), если требуется."""
    entry = PROVIDER_REGISTRY.get(account.type)
    if not entry:
        raise ValueError(f'Неизвестный тип облачного аккаунта: {account.type}')
    _, cls = entry
    return cls(account.config, account.secret)
