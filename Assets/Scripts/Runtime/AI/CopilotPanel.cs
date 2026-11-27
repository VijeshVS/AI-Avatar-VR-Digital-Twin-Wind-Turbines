using System.Collections;
using UnityEngine;
using UnityEngine.InputSystem;
using Vrar.Bootstrap;
using Vrar.Turbine;

namespace Vrar.AI
{
    /// <summary>
    /// "Ask the twin" panel. Sends one question to the grounded copilot and
    /// renders the answer, then performs the whitelisted actions it asked for —
    /// focus a component, switch scenario, scrub the clock.
    ///
    /// The answer is text, but the numbers inside it were computed by the health
    /// engine and handed to the model; the panel never does arithmetic on prose.
    /// F2 hides the panel so it does not cover the HUD on a narrow Game view.
    /// </summary>
    public sealed class CopilotPanel : MonoBehaviour
    {
        private static readonly string[] Presets =
        {
            "What is wrong with the turbine?",
            "Why is it failing?",
            "What should I do next?",
            "Explain it to a trainee.",
        };

        private static readonly Color PanelFill = new Color(0.05f, 0.06f, 0.08f, 0.92f);
        private static readonly Color Accent = new Color(1f, 0.78f, 0.30f);
        private static readonly Color Muted = new Color(0.62f, 0.66f, 0.72f);

        private const float MinPanelHeight = 440f;
        private const float Pad = 20f;
        private const float DesignHeight = 900f;

        [SerializeField] private MvpBootstrap _bootstrap;
        [SerializeField, Min(0.5f)] private float _timeoutSeconds = 20f;
        [SerializeField] private float _width = 640f;

        private CopilotClient _client;
        private string _question = Presets[0];
        private string _answer =
            "Ask about the machine. The copilot reads the live frame, so the answer changes as the turbine degrades.";
        private string _source = string.Empty;
        private string _status = "grounded on the live frame";
        private bool _busy;
        private bool _visible = true;

        private GUIStyle _title;
        private GUIStyle _caption;
        private GUIStyle _answerStyle;
        private float _styleScale = -1f;

        public bool Visible => _visible;
        public string Answer => _answer;
        public string Source => _source;

        public void Bind(MvpBootstrap bootstrap)
        {
            _bootstrap = bootstrap;
            _client = new CopilotClient(bootstrap.Endpoint, Mathf.RoundToInt(_timeoutSeconds));
        }

        private void Update()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard != null && keyboard.f2Key.wasPressedThisFrame)
            {
                _visible = !_visible;
            }
        }

        /// <summary>Ask one question. Ignored while a request is in flight.</summary>
        public void Ask(string question)
        {
            if (_busy || _bootstrap == null)
            {
                return;
            }

            _question = question;
            _busy = true;
            _status = "thinking…";
            StartCoroutine(AskRoutine(question));
        }

        private IEnumerator AskRoutine(string question)
        {
            _client ??= new CopilotClient(_bootstrap.Endpoint, Mathf.RoundToInt(_timeoutSeconds));

            Telemetry.TelemetryFrame frame = _bootstrap.LastFrame;
            CopilotReply reply = null;
            string error = null;
            yield return _client.Ask(
                question,
                frame?.elapsed_s ?? 0f,
                frame?.scenario,
                (result, failure) =>
                {
                    reply = result;
                    error = failure;
                });

            _busy = false;
            if (reply == null)
            {
                _status = "unavailable";
                _answer =
                    "The copilot is unreachable. Check that the telemetry service is running, then try again. "
                    + (error ?? string.Empty);
                yield break;
            }

            _answer = reply.answer;
            _source = reply.source;
            _status = reply.source == "llm"
                ? "answered by the model"
                : $"answered by rules ({reply.detail})";
            Apply(reply.actions);
        }

        private void Apply(CopilotAction[] actions)
        {
            if (actions == null || _bootstrap == null)
            {
                return;
            }

            foreach (CopilotAction action in actions)
            {
                if (action == null)
                {
                    continue;
                }

                switch (action.type)
                {
                    case CopilotAction.FocusComponent:
                        int index = IndexOfComponent(_bootstrap.Rig, action.component_id);
                        if (index >= 0)
                        {
                            _bootstrap.Focus?.Select(index);
                        }

                        break;

                    case CopilotAction.SetScenario:
                        if (!string.IsNullOrEmpty(action.scenario))
                        {
                            _bootstrap.SelectScenario(action.scenario);
                        }

                        break;

                    case CopilotAction.SetTime:
                        _bootstrap.SetPlaybackTime(Mathf.Max(0f, action.seconds));
                        break;
                }
            }
        }

        /// <summary>Avatar index for a component id, or -1. Exposed for the PlayMode suite.</summary>
        public static int IndexOfComponent(TurbineRig rig, string componentId)
        {
            if (rig == null || string.IsNullOrEmpty(componentId))
            {
                return -1;
            }

            for (int i = 0; i < rig.Avatars.Count; i++)
            {
                if (rig.Avatars[i] != null && rig.Avatars[i].ComponentId == componentId)
                {
                    return i;
                }
            }

            return -1;
        }

        private void OnGUI()
        {
            if (!_visible)
            {
                return;
            }

            float scale = UiScale;
            EnsureStyles(scale);

            float pad = Pad * scale;
            float maxWidth = Mathf.Min(Screen.width * 0.40f, Screen.width - 32f);
            float width = Mathf.Min(_width * scale, maxWidth);
            float height = Mathf.Max(MinPanelHeight, Screen.height - 32f);
            var panel = new Rect(Screen.width - width - 16f, 16f, width, height);
            float x = panel.x + pad;
            float inner = width - pad * 2f;
            float y = panel.y + 18f * scale;

            Color previous = GUI.color;
            GUI.color = PanelFill;
            GUI.DrawTexture(panel, Texture2D.whiteTexture);
            GUI.color = Accent;
            GUI.DrawTexture(new Rect(panel.x, panel.y, panel.width, 3f * scale), Texture2D.whiteTexture);
            GUI.color = previous;

            GUI.Label(new Rect(x, y, inner, 24f * scale), "AI COPILOT", _title);
            y += 24f * scale;
            GUI.Label(new Rect(x, y, inner, 18f * scale), StatusText(), _caption);
            y += 24f * scale;

            float gap = 8f * scale;
            float buttonWidth = (inner - gap) * 0.5f;
            for (int i = 0; i < Presets.Length; i++)
            {
                var button = new Rect(
                    x + (i % 2) * (buttonWidth + gap), y + (i / 2) * 40f * scale, buttonWidth, 34f * scale);
                if (GUI.Button(button, Presets[i]) && !_busy)
                {
                    Ask(Presets[i]);
                }
            }

            y += 88f * scale;
            float askWidth = 96f * scale;
            GUI.SetNextControlName("copilot-question");
            _question = GUI.TextField(
                new Rect(x, y, inner - askWidth - gap, 34f * scale), _question, 120);

            bool submitted = Event.current.type == EventType.KeyDown
                && (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter)
                && GUI.GetNameOfFocusedControl() == "copilot-question";
            if ((GUI.Button(new Rect(x + inner - askWidth, y, askWidth, 34f * scale), "Ask") || submitted)
                && !_busy)
            {
                Ask(_question);
                Event.current.Use();
            }

            y += 46f * scale;
            GUI.Label(new Rect(x, y, inner, height - (y - panel.y) - pad), _answer, _answerStyle);
        }

        /// <summary>
        /// IMGUI does not scale with the Game view, so the panel derives one factor
        /// from the viewport height: readable on a small window, larger on a big one.
        /// </summary>
        private static float UiScale => Mathf.Clamp(Screen.height / DesignHeight, 1f, 1.6f);

        private string StatusText()
        {
            if (_busy)
            {
                return "asking the copilot…";
            }

            return string.IsNullOrEmpty(_source) ? _status : $"{_status}  ·  F2 hides";
        }

        private void EnsureStyles(float scale)
        {
            if (_title != null && Mathf.Approximately(_styleScale, scale))
            {
                return;
            }

            _styleScale = scale;
            _title = new GUIStyle(GUI.skin.label)
            {
                fontSize = Mathf.RoundToInt(15f * scale),
                fontStyle = FontStyle.Bold,
                normal = { textColor = Accent },
            };
            _caption = new GUIStyle(GUI.skin.label)
            {
                fontSize = Mathf.RoundToInt(11f * scale),
                wordWrap = true,
                normal = { textColor = Muted },
            };
            _answerStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = Mathf.RoundToInt(14f * scale),
                wordWrap = true,
                alignment = TextAnchor.UpperLeft,
                clipping = TextClipping.Clip,
                normal = { textColor = new Color(0.88f, 0.90f, 0.93f) },
            };
            _answerStyle.padding = new RectOffset(2, 2, 2, 2);
        }
    }
}
