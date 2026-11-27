// The chat on the new map (map.html): the old interface's floating "Ask AI" button and dialog (chat-widget.js, chat.js,
// voice.js), the same markup and words, about the place on the card (or the area when none is). Gemini reads the
// app's flood data, Google Weather and Google Maps for it, as on the old page.
import { createChat } from "./chat.js";
import { createChatWidget } from "./chat-widget.js";
import { t } from "./i18n.js";
import * as realVoice from "./voice.js";

const $ = (id) => document.getElementById(id);

/** `area` is the map's area; `areas` the listed ones; getPlaceRef() the id of the place on the card, or null. */
export function createMapChat({ area, areas, status, getPlaceRef }) {
  const widget = createChatWidget({ button: $("chat-fab"), dialog: $("chat-dialog"), input: $("question"), onClose: realVoice.stopSpeaking });
  const chat = createChat({
    messages: $("messages"), chips: $("chips"), form: $("ask-form"), input: $("question"), news: $("news"), getPlaceRef,
    areaId: area.id, areaName: area.name, areas, isReady: status?.ai_ready === true, hasMaps: status?.maps_ready === true,
    voice: { ...realVoice, speak: (text, language) => widget.isOpen && realVoice.speak(text, language) },   // a late answer is not read to a closed chat
  });
  if (status?.ai_ready !== true) {
    $("ai-status").textContent = t("main.aiOff");
    $("ai-status").hidden = false;
  }
  if (status?.maps_ready !== true) $("ask-lead").textContent = t("ask.leadNoMaps");   // no Weather or Maps to read
  return {
    open: (opener = null) => widget.open(opener),
    /** The chips, the question box and the "About" line for the place now on the card. */
    render(place) {
      chat.render(place);
      const about = !place ? area.name : place.is_point ? t("ask.thisPoint") : place.name;
      $("chat-about").textContent = t("chat.about", { place: about });
    },
  };
}
