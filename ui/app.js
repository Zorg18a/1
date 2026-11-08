import { setupPreferences } from './preferences.js';
import { setupNotifications } from './notifications.js';
import { setupHotkeys } from './hotkeys.js';
import { setupJobEvents } from './job-events.js';
import { setupGameLibrary } from './game-library.js';
import { setupGameTags } from './game-tags.js';

const preferences = setupPreferences();
setupNotifications();
setupJobEvents();
setupHotkeys(preferences);
setupGameTags();
setupGameLibrary();
