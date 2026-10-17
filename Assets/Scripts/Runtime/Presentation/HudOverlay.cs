using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;
using Vrar.Health;
using Vrar.Turbine;

namespace Vrar.Presentation
{
    /// <summary>
    /// The plant readout, in two modes.
    ///
    /// <b>Overview</b> shows a plant roll-up and every component with its health
    /// bar, state chip and the reason behind its score. Clicking a row — or
    /// pressing 1-5 — enters focus mode on that component alone: the list is
    /// replaced by its full statistics, the camera flies to it and the other
    /// components go nearly transparent. A switcher grid and the number keys move
    /// between components without dropping back to the overview; Escape returns to
    /// it and flies the camera home.
    ///
    /// Deliberately IMGUI: a PoC HUD with no assets and no UI scene wiring.
    ///
    /// The panel sizes itself to its content. IMGUI has no flow layout, so every
    /// vertical extent is measured from the styles actually in use rather than
    /// guessed — otherwise enlarging the text silently clips the last row instead
    /// of growing the box around it. Each height is measured exactly once into
    /// <see cref="Layout"/> and reused by the drawing pass, so the box and its
    /// contents cannot disagree. Horizontal positions are fractions of that same
    /// measured width, and the panel is capped to the viewport, so text reflows
    /// rather than overlapping when the Game view is narrower than authored.
    ///
    /// No style is constructed inside a draw call: GUIStyle instances are cloned
    /// from the skin, so building one per label would allocate every frame.
    /// </summary>
    public sealed class HudOverlay : MonoBehaviour
    {
        private const string TitleText = "WIND TURBINE DIGITAL TWIN";
        private const string OverviewHint =
            "click a component or press 1-5 to focus  ·  Tab cycles  ·  Esc closes";
        private const string FocusHint =
            "← → or click to switch  ·  Tab cycles  ·  Esc shows all  ·  WASD takes back the camera";
        private const string ComponentsSection = "COMPONENTS";
        private const string FactorsSection = "WHY THIS SCORE";
        private const string SwitcherSection = "SWITCH COMPONENT";

        private static readonly Color PanelFill = new Color(0.05f, 0.06f, 0.08f, 0.88f);
        private static readonly Color Accent = new Color(1f, 0.78f, 0.30f);
        private static readonly Color Muted = new Color(0.62f, 0.66f, 0.72f);
        private static readonly Color Faint = new Color(0.42f, 0.46f, 0.52f);
        private static readonly Color TrackFill = new Color(1f, 1f, 1f, 0.10f);
        private static readonly Color PlateFill = new Color(1f, 1f, 1f, 0.06f);

        private const float PadX = 18f;
        private const float PadTop = 14f;
        private const float PadBottom = 14f;
        private const float AccentBarHeight = 3f;
        private const float LabelColumnWidth = 176f;
        private const float LabelGap = 16f;
        private const float ChipColumnWidth = 84f;
        private const float ChipGap = 12f;
        private const float BarHeight = 14f;
        private const float BarGap = 5f;
        private const float RowGap = 16f;
        private const float BlockGap = 10f;
        private const float TitleGap = 3f;
        private const float SeverityBarHeight = 12f;
        private const float SwitcherColumns = 3f;
        private const float SwitcherPadY = 8f;
        private const float SwitcherGap = 8f;
        private const float SwitcherDotSize = 12f;
        private const float MetricPadY = 6f;
        private const float ViewportMargin = 24f;

        // Fractions of the factor table width. They sum to 1, so the table always
        // ends flush with the panel edge and no column can be pushed off it.
        private const float SignalColumn = 0.34f;
        private const float ValueColumn = 0.17f;
        private const float WarnColumn = 0.10f;
        private const float CriticalColumn = 0.13f;
        private const float SeverityColumn = 0.14f;
        private const float ShareColumn = 0.12f;

        [SerializeField] private TurbineRig _rig;
        [SerializeField] private Telemetry.TelemetryFrame _lastFrame;
        [SerializeField] private bool _connected = true;
        [SerializeField] private string _statusLine = string.Empty;
        [SerializeField, Min(60f)] private float _width = 900f;

        private readonly ComponentFocus _focus = new ComponentFocus();
        private readonly List<string> _ids = new List<string>();
        private readonly List<Rect> _rowRects = new List<Rect>();
        private readonly List<Rect> _switcherRects = new List<Rect>();
        private readonly StringBuilder _builder = new StringBuilder();
        private readonly Dictionary<int, GUIStyle> _bigStyles = new Dictionary<int, GUIStyle>();

        private GUIStyle _title;
        private GUIStyle _subtitle;
        private GUIStyle _section;
        private GUIStyle _body;
        private GUIStyle _caption;
        private GUIStyle _detail;
        private GUIStyle _chipText;
        private GUIStyle _tableHeader;
        private GUIStyle _metricLabel;
        private GUIStyle _metricValue;
        private GUIStyle _hint;

        public ComponentFocus Focus => _focus;

        /// <summary>Panel width, capped so it never runs off a narrow Game view.</summary>
        private float PanelWidth => Mathf.Min(_width, Mathf.Max(320f, Screen.width - ViewportMargin));

        public void SetRig(TurbineRig rig)
        {
            _rig = rig;
        }

        public void SetFrame(Telemetry.TelemetryFrame frame, bool connected, string statusLine)
        {
            _lastFrame = frame;
            _connected = connected;
            _statusLine = statusLine;
        }

        /// <summary>Vertical extents measured for the current frame and focus.</summary>
        private struct Layout
        {
            public bool Focused;
            public float Width;
            public float Inner;
            public float X;
            public float Title;
            public float Subtitle;
            public float Section;
            public float Row;
            public float Summary;
            public float Big;
            public float Reason;
            public float Metrics;
            public float TableHeader;
            public float FactorRow;
            public float SwitcherItem;
            public float Switcher;
            public float Hint;
            public float PanelHeight;
        }

        private void Update()
        {
            SyncOrder();
            ReadKeyboard();
        }

        /// <summary>
        /// Keyboard focus switching. Digits map to the visible component order
        /// rather than to hardcoded ids, so the binding follows the rig instead of
        /// breaking when a component is added.
        /// </summary>
        private void ReadKeyboard()
        {
            Keyboard keyboard = Keyboard.current;
            if (keyboard == null)
            {
                return;
            }

            if (keyboard.escapeKey.wasPressedThisFrame)
            {
                _focus.Clear();
                return;
            }

            if (keyboard.tabKey.wasPressedThisFrame || keyboard.rightArrowKey.wasPressedThisFrame)
            {
                _focus.Cycle(1);
                return;
            }

            if (keyboard.leftArrowKey.wasPressedThisFrame)
            {
                _focus.Cycle(-1);
                return;
            }

            KeyControl[] digits =
            {
                keyboard.digit1Key, keyboard.digit2Key, keyboard.digit3Key,
                keyboard.digit4Key, keyboard.digit5Key, keyboard.digit6Key,
                keyboard.digit7Key, keyboard.digit8Key, keyboard.digit9Key,
            };

            for (int i = 0; i < digits.Length && i < _ids.Count; i++)
            {
                if (digits[i].wasPressedThisFrame)
                {
                    _focus.Select(i);
                    return;
                }
            }
        }

        private void OnGUI()
        {
            EnsureStyles();

            Layout layout = Measure();
            _rowRects.Clear();
            _switcherRects.Clear();

            DrawPanel(layout);

            float y = PadTop + layout.Title + TitleGap + layout.Subtitle + RowGap;
            if (layout.Focused)
            {
                DrawFocus(layout, y);
            }
            else
            {
                DrawOverview(layout, y);
            }

            GUI.Label(new Rect(layout.X, PadTop + layout.PanelHeight - PadBottom - layout.Hint, layout.Inner, layout.Hint),
                HintText(layout.Focused), _hint);

            HandleClicks();
        }

        /// <summary>
        /// The dark panel, its accent rule and the header. Drawn rather than styled
        /// so the fill can be translucent over the scene.
        /// </summary>
        private void DrawPanel(Layout layout)
        {
            var panel = new Rect(16f, 16f, layout.Width, layout.PanelHeight);
            Color previous = GUI.color;

            GUI.color = PanelFill;
            GUI.DrawTexture(panel, Texture2D.whiteTexture);

            GUI.color = Accent;
            GUI.DrawTexture(new Rect(panel.x, panel.y, panel.width, AccentBarHeight), Texture2D.whiteTexture);

            GUI.color = previous;
            GUI.Label(new Rect(layout.X, PadTop, layout.Inner, layout.Title), TitleText, _title);
            GUI.Label(new Rect(layout.X, PadTop + layout.Title + TitleGap, layout.Inner, layout.Subtitle),
                StatusText(), _subtitle);
        }

        private void DrawOverview(Layout layout, float y)
        {
            DrawSection(ComponentsSection, layout.X, y, layout.Inner, layout.Section);
            y += layout.Section + BlockGap;

            int componentCount = _rig?.Avatars.Count ?? 0;
            for (int i = 0; i < componentCount; i++)
            {
                Rect row = new Rect(layout.X, y, layout.Inner, layout.Row);
                _rowRects.Add(row);
                DrawComponentRow(i, row, layout);
                y += layout.Row;
            }

            y += RowGap;
            GUI.Label(new Rect(layout.X, y, layout.Inner, layout.Summary), PlantSummary(), _caption);
        }

        /// <summary>
        /// Plant-level roll-up: how many components sit in each band, so the
        /// overview answers "is anything wrong" before any row is read.
        /// </summary>
        private string PlantSummary()
        {
            int critical = 0;
            int watch = 0;
            Avatar.ComponentAvatar worst = null;
            float worstHealth = 1f;

            if (_rig != null)
            {
                foreach (Avatar.ComponentAvatar avatar in _rig.Avatars)
                {
                    if (avatar == null)
                    {
                        continue;
                    }

                    if (avatar.Health < HealthPalette.AlarmThreshold)
                    {
                        critical++;
                    }
                    else if (avatar.Health < HealthPalette.WatchThreshold)
                    {
                        watch++;
                    }

                    if (avatar.Health < worstHealth)
                    {
                        worstHealth = avatar.Health;
                        worst = avatar;
                    }
                }
            }

            _builder.Clear();
            _builder.Append(worst == null ? "no components" : $"worst {worst.Label} {worst.Health * 100f:0}%");
            _builder.Append($"     {critical} critical     {watch} watch");
            return _builder.ToString();
        }

        private void DrawComponentRow(int index, Rect row, Layout layout)
        {
            Avatar.ComponentAvatar avatar = _rig.Avatars[index];
            float health = avatar.Health;
            Color color = HealthPalette.ColorFor(health);

            float barWidth = layout.Inner - LabelColumnWidth - LabelGap - ChipColumnWidth - ChipGap;
            float barX = layout.X + LabelColumnWidth + LabelGap;

            float labelHeight = _body.CalcHeight(new GUIContent(avatar.Label), LabelColumnWidth);
            float barY = row.y + Mathf.Max(0f, (labelHeight - BarHeight) * 0.5f);
            GUI.Label(new Rect(row.x, row.y, LabelColumnWidth, labelHeight), avatar.Label, _body);

            DrawHealthBar(new Rect(barX, barY, barWidth, BarHeight), health, color);

            float captionY = barY + BarHeight + BarGap;
            Telemetry.ComponentPayload component = _lastFrame?.Component(avatar.ComponentId);
            string reason = component != null ? component.PrimaryReason() : string.Empty;
            GUI.Label(new Rect(row.x, captionY, layout.Inner - ChipColumnWidth - ChipGap,
                row.y + row.height - captionY), reason, _caption);

            DrawChip(new Rect(row.x + layout.Inner - ChipColumnWidth, barY - 1f, ChipColumnWidth, labelHeight),
                $"{health * 100f:0}%", color);
        }

        /// <summary>A health bar with its warn and critical thresholds ticked.</summary>
        private static void DrawHealthBar(Rect bar, float health, Color color)
        {
            Color previous = GUI.color;
            GUI.color = TrackFill;
            GUI.DrawTexture(bar, Texture2D.whiteTexture);

            GUI.color = color;
            GUI.DrawTexture(new Rect(bar.x, bar.y, bar.width * Mathf.Clamp01(health), bar.height), Texture2D.whiteTexture);

            // Threshold ticks, so the reader can see how close the bar is to the
            // next band rather than only which band it is in.
            GUI.color = new Color(0f, 0f, 0f, 0.5f);
            foreach (float threshold in new[] { HealthPalette.WatchThreshold, HealthPalette.AlarmThreshold })
            {
                float x = bar.x + bar.width * threshold;
                GUI.DrawTexture(new Rect(x - 1f, bar.y - 2f, 2f, bar.height + 4f), Texture2D.whiteTexture);
            }

            GUI.color = previous;
        }

        private void DrawChip(Rect rect, string text, Color color)
        {
            Color previous = GUI.color;
            GUI.color = new Color(color.r, color.g, color.b, 0.24f);
            GUI.DrawTexture(rect, Texture2D.whiteTexture);
            GUI.color = color;
            GUI.Label(rect, text, _chipText);
            GUI.color = previous;
        }

        private void DrawFocus(Layout layout, float y)
        {
            Avatar.ComponentAvatar avatar = _rig?.Avatar(_focus.ComponentId);
            Telemetry.ComponentPayload component = _lastFrame?.Component(_focus.ComponentId);
            Telemetry.FactorPayload[] factors = component?.factors ?? Array.Empty<Telemetry.FactorPayload>();
            float health = avatar != null ? avatar.Health : component?.health ?? 1f;
            Color color = HealthPalette.ColorFor(health);

            DrawSection($"FOCUS — {(avatar != null ? avatar.Label : "component").ToUpperInvariant()}",
                layout.X, y, layout.Inner, layout.Section);
            y += layout.Section + BlockGap;

            // The headline: health spelled out large, with the state beside it so
            // the reading never depends on colour alone.
            GUI.Label(new Rect(layout.X, y, layout.Inner * 0.35f, layout.Big), $"{health * 100f:0}%", BigStyle(color));
            GUI.Label(new Rect(layout.X + layout.Inner * 0.35f, y, layout.Inner * 0.65f, layout.Big),
                (component?.state ?? HealthPalette.StateFor(health)).ToUpperInvariant(), BigStyle(color));
            y += layout.Big + TitleGap;

            GUI.Label(new Rect(layout.X, y, layout.Inner, layout.Reason), ReasonText(component), _detail);
            y += layout.Reason + BlockGap;

            DrawMetrics(layout, component, avatar, y);
            y += layout.Metrics + BlockGap;

            DrawFactorTable(layout, factors, y);
            y += layout.Section + BlockGap + layout.TableHeader + TitleGap
                 + factors.Length * layout.FactorRow + BlockGap;

            DrawSection(SwitcherSection, layout.X, y, layout.Inner, layout.Section);
            DrawSwitcher(layout, y + layout.Section + BlockGap);
        }

        /// <summary>
        /// Three headline measurements. Vibration and trend are the numbers an
        /// engineer asks for first; the share is how much of the score the worst
        /// single signal is actually responsible for.
        /// </summary>
        private void DrawMetrics(Layout layout, Telemetry.ComponentPayload component,
            Avatar.ComponentAvatar avatar, float y)
        {
            float tileWidth = layout.Inner / 3f;
            string share = "—";
            if (component != null && component.factors != null && component.factors.Length > 0 &&
                component.factors[0] != null)
            {
                share = $"{component.factors[0].contribution * 100f:0} %";
            }

            DrawMetric("VIBRATION", avatar != null ? $"{avatar.VibrationAmplitude:0.00} mm/s" : "—",
                layout.X, y, tileWidth, layout);
            DrawMetric("TREND /S", component != null ? $"{component.trend:+0.000;-0.000;0.000}" : "—",
                layout.X + tileWidth, y, tileWidth, layout);
            DrawMetric("TOP FACTOR SHARE", share, layout.X + tileWidth * 2f, y, tileWidth, layout);
        }

        private void DrawMetric(string label, string value, float x, float y, float width, Layout layout)
        {
            var plate = new Rect(x, y, width - SwitcherGap, layout.Metrics);
            Color previous = GUI.color;
            GUI.color = PlateFill;
            GUI.DrawTexture(plate, Texture2D.whiteTexture);
            GUI.color = previous;

            GUI.Label(new Rect(plate.x + MetricPadY * 2f, plate.y + MetricPadY, plate.width, _metricLabel.CalcHeight(
                new GUIContent(label), plate.width)), label, _metricLabel);
            GUI.Label(new Rect(plate.x + MetricPadY * 2f, plate.y + MetricPadY + _metricLabel.CalcHeight(
                new GUIContent(label), plate.width), plate.width, plate.height - MetricPadY * 2f
                - _metricLabel.CalcHeight(new GUIContent(label), plate.width)), value, _metricValue);
        }

        private void DrawFactorTable(Layout layout, Telemetry.FactorPayload[] factors, float y)
        {
            DrawSection(FactorsSection, layout.X, y, layout.Inner, layout.Section);
            y += layout.Section + BlockGap;

            float cursor = layout.X;
            float w = layout.Inner;
            cursor = DrawHeaderCell("SIGNAL", cursor, w * SignalColumn, y);
            cursor = DrawHeaderCell("VALUE", cursor, w * ValueColumn, y);
            cursor = DrawHeaderCell("WARN", cursor, w * WarnColumn, y);
            cursor = DrawHeaderCell("CRITICAL", cursor, w * CriticalColumn, y);
            cursor = DrawHeaderCell("SEVERITY", cursor, w * SeverityColumn, y);
            DrawHeaderCell("SHARE", cursor, w * ShareColumn, y);
            y += layout.TableHeader + TitleGap;

            for (int i = 0; i < factors.Length; i++)
            {
                DrawFactorRow(factors[i], layout, y);
                y += layout.FactorRow;
            }
        }

        private float DrawHeaderCell(string text, float x, float width, float y)
        {
            GUI.Label(new Rect(x, y, width, _tableHeader.CalcHeight(new GUIContent(text), width)), text, _tableHeader);
            return x + width;
        }

        private void DrawFactorRow(Telemetry.FactorPayload factor, Layout layout, float y)
        {
            if (factor == null)
            {
                return;
            }

            float cursor = layout.X;
            float w = layout.Inner;
            float textHeight = layout.FactorRow - BarGap - 6f;

            GUI.Label(new Rect(cursor, y, w * SignalColumn, textHeight), factor.signal, _detail);
            cursor += w * SignalColumn;
            GUI.Label(new Rect(cursor, y, w * ValueColumn, textHeight), $"{factor.value:0.00} {factor.unit}", _detail);
            cursor += w * ValueColumn;
            GUI.Label(new Rect(cursor, y, w * WarnColumn, textHeight), $"{factor.warn:0.00}", _detail);
            cursor += w * WarnColumn;
            GUI.Label(new Rect(cursor, y, w * CriticalColumn, textHeight), $"{factor.critical:0.00}", _detail);
            cursor += w * CriticalColumn;

            float severityWidth = w * SeverityColumn;
            var severityBar = new Rect(cursor, y + (textHeight - SeverityBarHeight) * 0.5f, severityWidth, SeverityBarHeight);
            Color previous = GUI.color;
            GUI.color = TrackFill;
            GUI.DrawTexture(severityBar, Texture2D.whiteTexture);
            GUI.color = HealthPalette.ColorFor(1f - factor.severity);
            GUI.DrawTexture(new Rect(severityBar.x, severityBar.y, severityBar.width * factor.severity, severityBar.height),
                Texture2D.whiteTexture);
            GUI.color = previous;
            cursor += severityWidth;

            GUI.Label(new Rect(cursor, y, w * ShareColumn, textHeight), $"{factor.contribution * 100f:0} %", _detail);
        }

        /// <summary>
        /// The component switcher. Focus mode hides the overview list, so without
        /// this the only ways to change component would be keys. A fixed-column
        /// grid rather than one line, because five component labels do not fit
        /// across a single row at a readable size.
        /// </summary>
        private void DrawSwitcher(Layout layout, float y)
        {
            int componentCount = _rig?.Avatars.Count ?? 0;
            if (componentCount == 0)
            {
                return;
            }

            int columns = Mathf.RoundToInt(SwitcherColumns);
            float itemWidth = layout.Inner / SwitcherColumns;
            float textHeight = layout.SwitcherItem - SwitcherPadY * 2f;

            for (int i = 0; i < componentCount; i++)
            {
                Avatar.ComponentAvatar avatar = _rig.Avatars[i];
                bool active = _focus.Index == i;
                Color color = HealthPalette.ColorFor(avatar.Health);

                var item = new Rect(
                    layout.X + (i % columns) * itemWidth,
                    y + (i / columns) * (layout.SwitcherItem + SwitcherGap),
                    itemWidth - SwitcherGap,
                    layout.SwitcherItem);
                _switcherRects.Add(item);

                Color previous = GUI.color;
                GUI.color = active ? new Color(1f, 1f, 1f, 0.15f) : PlateFill;
                GUI.DrawTexture(item, Texture2D.whiteTexture);

                if (active)
                {
                    GUI.color = Accent;
                    GUI.DrawTexture(new Rect(item.x, item.y + 3f, 3f, item.height - 6f), Texture2D.whiteTexture);
                }

                GUI.color = color;
                GUI.DrawTexture(new Rect(
                    item.x + 12f,
                    item.y + (item.height - SwitcherDotSize) * 0.5f,
                    SwitcherDotSize,
                    SwitcherDotSize), Texture2D.whiteTexture);
                GUI.color = previous;

                float textX = item.x + 12f + SwitcherDotSize + 10f;
                GUI.Label(new Rect(textX, item.y + SwitcherPadY, item.width - (textX - item.x) - 12f, textHeight),
                    $"{i + 1}  {avatar.Label}   {avatar.Health * 100f:0}%", active ? _chipText : _caption);
            }
        }

        private Layout Measure()
        {
            int componentCount = _rig?.Avatars.Count ?? 0;
            float width = PanelWidth;
            float inner = width - 2f * PadX;

            Telemetry.ComponentPayload focused = _focus.HasFocus
                ? _lastFrame?.Component(_focus.ComponentId)
                : null;
            Telemetry.FactorPayload[] factors = focused?.factors ?? Array.Empty<Telemetry.FactorPayload>();

            var layout = new Layout
            {
                Width = width,
                Inner = inner,
                X = 16f + PadX,
                Focused = _focus.HasFocus && componentCount > 0,
                Title = _title.CalcHeight(new GUIContent(TitleText), inner),
                Subtitle = _subtitle.CalcHeight(new GUIContent(StatusText()), inner),
                Section = _section.CalcHeight(new GUIContent(ComponentsSection), inner),
                Row = RowHeight(),
                Summary = _caption.CalcHeight(new GUIContent("worst Gearbox 4%"), inner),
                Big = _caption.CalcHeight(new GUIContent("100%"), inner) * 2f,
                Reason = _detail.CalcHeight(new GUIContent(ReasonText(null)), inner),
                TableHeader = _tableHeader.CalcHeight(new GUIContent("SIGNAL"), inner),
                Hint = _hint.CalcHeight(new GUIContent(HintText(_focus.HasFocus)), inner),
            };

            layout.Metrics = MetricHeight();
            layout.FactorRow = FactorRowHeight();
            layout.SwitcherItem = _caption.CalcHeight(new GUIContent("1 Blade Set 100%"), inner / SwitcherColumns)
                                 + SwitcherPadY * 2f;
            int switcherRows = Mathf.Max(1, Mathf.CeilToInt(componentCount / SwitcherColumns));
            layout.Switcher = switcherRows * layout.SwitcherItem + (switcherRows - 1) * SwitcherGap;

            float content = layout.Title + TitleGap + layout.Subtitle + RowGap;

            if (layout.Focused)
            {
                content += layout.Section + BlockGap
                           + layout.Big + TitleGap + layout.Reason + BlockGap
                           + layout.Metrics + BlockGap
                           + layout.Section + BlockGap + layout.TableHeader + TitleGap
                           + factors.Length * layout.FactorRow + BlockGap
                           + layout.Section + BlockGap + layout.Switcher;
            }
            else
            {
                content += layout.Section + BlockGap + componentCount * layout.Row + RowGap + layout.Summary;
            }

            content += RowGap + layout.Hint;
            layout.PanelHeight = PadTop + content + PadBottom;
            return layout;
        }

        private static float MetricHeight()
        {
            return 20f + MetricPadY * 2f + 4f;
        }

        /// <summary>Height of one overview row: label and bar, then the reason line.</summary>
        private float RowHeight()
        {
            float labelHeight = _body.CalcHeight(new GUIContent("Component"), LabelColumnWidth);
            float captionHeight = _caption.CalcHeight(new GUIContent("reason"), 400f);
            return Mathf.Max(labelHeight, BarHeight) + BarGap + captionHeight + BlockGap;
        }

        /// <summary>Height of one factor row: its text and its severity bar.</summary>
        private static float FactorRowHeight()
        {
            return 22f;
        }

        // The headline percentage is coloured per health band, so it needs a style
        // per colour rather than one shared instance.
        private GUIStyle BigStyle(Color color)
        {
            var key = (Color32)color;
            int hash = key.r << 16 | key.g << 8 | key.b;
            if (_bigStyles.TryGetValue(hash, out GUIStyle cached) && cached != null)
            {
                return cached;
            }

            var style = Make(44, FontStyle.Bold, color);
            _bigStyles[hash] = style;
            return style;
        }

        private void DrawSection(string text, float x, float y, float width, float height)
        {
            Color previous = GUI.color;
            GUI.color = Accent;
            GUI.DrawTexture(new Rect(x, y + 2f, 3f, height - 4f), Texture2D.whiteTexture);
            GUI.color = previous;
            GUI.Label(new Rect(x + 10f, y, width - 10f, height), text, _section);
        }

        private static string ReasonText(Telemetry.ComponentPayload component)
        {
            return component == null ? "no frame data for this component yet" : component.PrimaryReason();
        }

        private static string HintText(bool focused)
        {
            return focused ? FocusHint : OverviewHint;
        }

        private void HandleClicks()
        {
            Event current = Event.current;
            if (current == null || current.type != EventType.MouseDown || current.button != 0)
            {
                return;
            }

            // Switcher first: in focus mode it is the only clickable list on screen.
            for (int i = 0; i < _switcherRects.Count; i++)
            {
                if (_switcherRects[i].Contains(current.mousePosition))
                {
                    _focus.Select(i);
                    current.Use();
                    return;
                }
            }

            for (int i = 0; i < _rowRects.Count; i++)
            {
                if (!_rowRects[i].Contains(current.mousePosition))
                {
                    continue;
                }

                // Clicking the focused row again closes it, so the same gesture
                // both opens and dismisses.
                if (_focus.HasFocus && _focus.Index == i)
                {
                    _focus.Clear();
                }
                else
                {
                    _focus.Select(i);
                }

                current.Use();
                return;
            }
        }

        private void SyncOrder()
        {
            _ids.Clear();
            if (_rig != null)
            {
                foreach (Avatar.ComponentAvatar avatar in _rig.Avatars)
                {
                    _ids.Add(avatar.ComponentId);
                }
            }

            _focus.SetOrder(_ids);
        }

        private string StatusText()
        {
            if (!_connected)
            {
                return _statusLine.Length > 0 ? $"OFFLINE — {_statusLine}" : "OFFLINE — waiting for telemetry";
            }

            _builder.Clear();
            _builder.Append(_statusLine);
            if (_lastFrame != null)
            {
                _builder.Append($"    t={_lastFrame.elapsed_s:0}s    {_lastFrame.scenario}");
            }

            return _builder.ToString();
        }

        private void EnsureStyles()
        {
            if (_title != null)
            {
                return;
            }

            _title = Make(26, FontStyle.Bold, Color.white);
            _subtitle = Make(16, FontStyle.Normal, Muted);
            _section = Make(14, FontStyle.Bold, Muted);
            _body = Make(22, FontStyle.Normal, Color.white);
            _caption = Make(17, FontStyle.Normal, new Color(0.80f, 0.84f, 0.88f));
            _detail = Make(16, FontStyle.Normal, new Color(0.86f, 0.88f, 0.90f));
            _chipText = Make(18, FontStyle.Bold, Color.white);
            _chipText.alignment = TextAnchor.MiddleCenter;
            _tableHeader = Make(13, FontStyle.Bold, Faint);
            _metricLabel = Make(12, FontStyle.Bold, Faint);
            _metricValue = Make(20, FontStyle.Normal, Color.white);
            _hint = Make(15, FontStyle.Normal, Faint);
        }

        private static GUIStyle Make(int size, FontStyle style, Color color)
        {
            var made = new GUIStyle(GUI.skin.label) { fontSize = size, fontStyle = style };
            made.normal.textColor = color;
            return made;
        }
    }
}