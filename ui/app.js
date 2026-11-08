import { setupPreferences } from './preferences.js';
import { setupNotifications } from './notifications.js';
import { setupHotkeys } from './hotkeys.js';
import { setupJobEvents } from './job-events.js';

const preferences = setupPreferences();
setupNotifications();
setupJobEvents();
setupHotkeys(preferences);
