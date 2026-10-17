using System;
using UnityEngine;
using UnityEngine.Rendering;
using Vrar.Health;

namespace Vrar.Avatar
{
    /// <summary>
    /// How prominently an avatar is drawn while a component is focused.
    /// </summary>
    public enum FocusState
    {
        Normal,
        Focused,
        Dimmed
    }

    /// <summary>
    /// One turbine component rendered as an avatar: it carries a material, a
    /// vibration signal from telemetry and an optional audio source, and it
    /// expresses its health perceptually instead of printing a number.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class ComponentAvatar : MonoBehaviour
    {
        [Header("Identity")]
        [SerializeField] private string _componentId = "gearbox";
        [SerializeField] private string _label = "Gearbox";

        [Header("Expression")]
        [SerializeField, Range(0f, 1f)] private float _health = 1f;
        [SerializeField, Min(0f)] private float _vibrationAmplitude;
        [SerializeField, Min(0f)] private float _vibrationHz = 12f;
        [SerializeField, Min(0f)] private float _emissionScale = 2.5f;
        [SerializeField, Range(0.02f, 1f)] private float _dimmedAlpha = 0.06f;
        [SerializeField] private Renderer[] _renderers = Array.Empty<Renderer>();

        private MaterialPropertyBlock _propertyBlock;
        private Vector3 _restPosition;
        private float _noiseSeed;
        private AudioSource _alarmSource;
        private float _alarmPhase;
        private FocusState _focusState = FocusState.Normal;
        private MaterialBlendState[] _blendStates = Array.Empty<MaterialBlendState>();

        public string ComponentId => _componentId;
        public string Label => _label;
        public float Health => _health;
        public float VibrationAmplitude => _vibrationAmplitude;
        public Color CurrentColor => HealthPalette.ColorFor(_health);
        public FocusState Focus => _focusState;

        public void Configure(string componentId, string label, Renderer[] renderers)
        {
            _componentId = componentId;
            _label = label;
            if (renderers != null && renderers.Length > 0)
            {
                _renderers = renderers;
                EnableEmission();
                // Renderers can arrive after a focus state was already requested,
                // in which case the blend mode still has to be applied to them.
                if (_focusState != FocusState.Normal)
                {
                    ApplyBlendMode();
                }
            }
        }

        public void AttachAlarm(AudioSource source)
        {
            _alarmSource = source;
        }

        /// <summary>
        /// Promote or demote this avatar for focus mode.
        ///
        /// Dimming needs more than an alpha in the property block: URP only blends
        /// a material while the transparent variant of its shader is active, and
        /// that is a material-level keyword rather than a per-renderer value. Each
        /// avatar already owns a private material copy (see
        /// <c>TurbineFactory.GiveAvatarMaterial</c>), so switching the blend mode
        /// here cannot leak into the rest of the rig.
        /// </summary>
        public void SetFocusState(FocusState state)
        {
            if (_focusState == state)
            {
                return;
            }

            _focusState = state;
            ApplyBlendMode();
        }

        /// <summary>Apply a telemetry component payload. Safe to call every frame.</summary>
        public void Apply(Vrar.Telemetry.ComponentPayload component)
        {
            if (component == null)
            {
                return;
            }

            _health = Mathf.Clamp01(component.health);
            _label = string.IsNullOrEmpty(component.label) ? _label : component.label;
        }

        /// <summary>Apply the vibration amplitude carried by the plant signals (mm/s).</summary>
        public void SetVibration(float millimetresPerSecond)
        {
            _vibrationAmplitude = Mathf.Max(0f, millimetresPerSecond);
        }

        private void Awake()
        {
            _propertyBlock = new MaterialPropertyBlock();
            _restPosition = transform.localPosition;
            _noiseSeed = UnityEngine.Random.Range(0f, 100f);
            EnableEmission();
        }

        /// <summary>
        /// Turn on emission, which is the second perceptual channel after colour.
        /// URP ignores <c>_EmissionColor</c> entirely while the keyword is off, and
        /// the keyword does not survive being written into a scene at build time,
        /// so it is re-asserted from script. Called both at Awake and on
        /// <see cref="Configure"/>, because the renderers arrive after the
        /// component is added.
        /// </summary>
        private void EnableEmission()
        {
            foreach (Renderer target in _renderers)
            {
                if (target != null && target.sharedMaterial != null)
                {
                    target.sharedMaterial.EnableKeyword("_EMISSION");
                }
            }
        }

        private void Update()
        {
            float distress = HealthPalette.Distress(_health);
            ApplyColor(distress);
            ApplyTremor(distress);
            UpdateAlarm(distress);
        }

        private void ApplyColor(float distress)
        {
            Color color = HealthPalette.ColorFor(_health, _focusState == FocusState.Dimmed ? _dimmedAlpha : 1f);

            // Failing parts glow harder and breathe faster: the pulse rate rises
            // with distress so degradation is legible from across the room. The
            // focused part out-glows its neighbours; the dimmed ones barely glow,
            // so the eye is not pulled off the component under inspection.
            float gain = _focusState == FocusState.Focused ? 1.4f
                : _focusState == FocusState.Dimmed ? 0.08f
                : 1f;
            float pulse = 0.75f + 0.25f * Mathf.Sin(Time.time * Mathf.Lerp(1.5f, 6f, distress) + _noiseSeed);
            float emission = Mathf.Lerp(0.15f, _emissionScale, distress * distress) * pulse * gain;

            foreach (Renderer target in _renderers)
            {
                if (target == null)
                {
                    continue;
                }

                target.GetPropertyBlock(_propertyBlock);
                _propertyBlock.SetColor("_BaseColor", color);
                _propertyBlock.SetColor("_Color", color);
                _propertyBlock.SetColor("_EmissionColor", color * emission);
                target.SetPropertyBlock(_propertyBlock);
            }
        }

        /// <summary>
        /// Switch the avatar's private materials between the opaque and
        /// transparent blend modes, and stop dimmed parts casting shadows — a
        /// translucent part that still casts a solid shadow reads as broken.
        /// The authored settings are captured once and restored exactly.
        /// </summary>
        private void ApplyBlendMode()
        {
            bool dimmed = _focusState == FocusState.Dimmed;

            // Sized here rather than in Configure: a rig loaded from the scene has
            // its renderers deserialised and never passes through Configure, so
            // this is the only place both paths are guaranteed to go through.
            if (_blendStates.Length != _renderers.Length)
            {
                _blendStates = new MaterialBlendState[_renderers.Length];
            }

            for (int i = 0; i < _renderers.Length; i++)
            {
                Renderer target = _renderers[i];
                if (target == null)
                {
                    continue;
                }

                if (_blendStates[i] == null)
                {
                    _blendStates[i] = new MaterialBlendState(target.sharedMaterial);
                }

                if (dimmed)
                {
                    _blendStates[i].SetTransparent();
                }
                else
                {
                    _blendStates[i].SetOpaque();
                }

                target.shadowCastingMode = dimmed ? ShadowCastingMode.Off : ShadowCastingMode.On;
            }
        }

        private void ApplyTremor(float distress)
        {
            if (distress <= 0.01f)
            {
                transform.localPosition = _restPosition;
                return;
            }

            float amplitude = _vibrationAmplitude * 0.0015f * (0.3f + distress);
            float time = Time.time * _vibrationHz;
            Vector3 offset = new Vector3(
                (Mathf.PerlinNoise(_noiseSeed, time) - 0.5f) * 2f,
                (Mathf.PerlinNoise(time, _noiseSeed) - 0.5f) * 2f,
                (Mathf.PerlinNoise(time + 31.4f, _noiseSeed + 7.1f) - 0.5f) * 2f);
            transform.localPosition = _restPosition + offset * amplitude;
        }

        private void UpdateAlarm(float distress)
        {
            if (_alarmSource == null)
            {
                return;
            }

            if (distress < 0.55f)
            {
                _alarmSource.Stop();
                _alarmSource.volume = 0f;
                return;
            }

            float rate = Mathf.Lerp(0.6f, 3.2f, Mathf.InverseLerp(0.55f, 1f, distress));
            _alarmPhase += Time.deltaTime * rate;
            float beep = Mathf.PingPong(_alarmPhase, 1f);
            // An alarm that cannot be heard is not an alarm: the floor is set so
            // the very first beep at the critical threshold is already clearly
            // audible, rather than only becoming loud once the part is nearly dead.
            _alarmSource.volume = Mathf.Lerp(0.6f, 1f, Mathf.InverseLerp(0.55f, 1f, distress))
                                  * (1f - Mathf.Abs(beep - 0.5f) * 2f);

            if (!_alarmSource.isPlaying)
            {
                _alarmSource.Play();
            }
        }

#if UNITY_EDITOR
        private void OnDrawGizmosSelected()
        {
            Gizmos.color = HealthPalette.ColorFor(_health);
            Gizmos.DrawWireSphere(transform.position, 1.5f);
        }
#endif
    }
}