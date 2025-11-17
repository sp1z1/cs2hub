# views/web_engine.py
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

class ExternalLinkPage(QWebEnginePage):
    """Собственная страница для обработки ссылок во внешнем браузере."""
    def acceptNavigationRequest(self, url: QUrl, type: QWebEnginePage.NavigationType, isMainFrame: bool) -> bool:
        if type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ('http', 'https'):
            QDesktopServices.openUrl(url)
            return False
        
        return super().acceptNavigationRequest(url, type, isMainFrame)