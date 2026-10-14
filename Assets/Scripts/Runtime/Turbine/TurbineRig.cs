using System;
using System.Collections.Generic;
using UnityEngine;
using Vrar.Avatar;
using Vrar.Health;
using Vrar.Telemetry;

namespace Vrar.Turbine
{
    /// <summary>
    /// Owns the turbine avatars and applies a telemetry frame to them: rotor
    /// speed from the service's rotor azimuth, blade pitch and imbalance wobble,
    /// and each component's health and vibration amplitude.
    ///
    /// This is the whole point of the PoC in one method - <see cref="Apply"/> is
    /// the seam the PlayMode tests assert against.
    /// </summary>
    public sealed class TurbineRig : MonoBehaviour
    {
        private readonly List<ComponentAvatar> _avatars = new List<ComponentAvatar>();
        private readonly Dictionary<string, ComponentAvatar> _byId = new Dictionary<string, ComponentAvatar>();
        private readonly List<Transform> _blades = new List<Transform>();

        private Transform _rotor;
        private Transform _bladeSet;
        private Quaternion[] _bladeRestRotations = Array.Empty<Quaternion>();

        public IReadOnlyList<ComponentAvatar> Avatars => _avatars;
        public Transform Rotor => _rotor;
        public TelemetryFrame LastFrame { get; private set; }

        /// <summary>
        /// Rebuild the lookup tables from the hierarchy.
        ///
        /// A rig built in the Editor has its caches populated by
        /// <see cref="Assign"/>, but those are plain C# collections and are not
        /// serialised: a rig loaded from a scene would come back empty and silently
        /// drop every frame. Resolving from the hierarchy makes scene-loaded and
        /// runtime-built rigs behave identically.
        /// </summary>
        private void Awake()
        {
            ResolveFromHierarchy();
        }

        public void Assign(
            IReadOnlyList<ComponentAvatar> avatars, Transform rotor, Transform bladeSet, IReadOnlyList<Transform> blades)
        {
            _avatars.Clear();
            _byId.Clear();
            _blades.Clear();

            foreach (ComponentAvatar avatar in avatars)
            {
                _avatars.Add(avatar);
                _byId[avatar.ComponentId] = avatar;
            }

            _rotor = rotor;
            _bladeSet = bladeSet;
            _blades.Clear();
            for (int i = 0; i < blades.Count; i++)
            {
                _blades.Add(blades[i]);
            }

            CacheBladeRestRotations();
        }

        public void ResolveFromHierarchy()
        {
            _avatars.Clear();
            _byId.Clear();
            _blades.Clear();

            foreach (ComponentAvatar avatar in GetComponentsInChildren<ComponentAvatar>(true))
            {
                _avatars.Add(avatar);
                _byId[avatar.ComponentId] = avatar;
            }

            _rotor = FindDeep("Rotor") ?? _rotor;
            _bladeSet = FindDeep("BladeSet") ?? _bladeSet;

            if (_bladeSet != null)
            {
                foreach (Transform child in _bladeSet)
                {
                    _blades.Add(child);
                }
            }

            CacheBladeRestRotations();
        }

        private Transform FindDeep(string name)
        {
            foreach (Transform candidate in GetComponentsInChildren<Transform>(true))
            {
                if (candidate.name == name)
                {
                    return candidate;
                }
            }

            return null;
        }

        private void CacheBladeRestRotations()
        {
            _bladeRestRotations = new Quaternion[_blades.Count];
            for (int i = 0; i < _blades.Count; i++)
            {
                _bladeRestRotations[i] = _blades[i].localRotation;
            }
        }

        public ComponentAvatar Avatar(string componentId)
        {
            return _byId.TryGetValue(componentId, out ComponentAvatar avatar) ? avatar : null;
        }

        /// <summary>Push one telemetry frame into the scene graph.</summary>
        public void Apply(TelemetryFrame frame)
        {
            if (frame == null)
            {
                return;
            }

            if (_byId.Count == 0)
            {
                // Apply can run before Awake (edit-mode tests) or on a rig whose
                // caches were never populated.
                ResolveFromHierarchy();
            }

            LastFrame = frame;
            ApplyRotor(frame);
            ApplyBladeAttitude(frame);

            float nacelleVibration = frame.Signal("nacelle_vibration_mm_s");
            float gearboxVibration = frame.Signal("gearbox_vibration_mm_s");
            float windingTemp = frame.Signal("generator_winding_temp_c");
            float pitchError = frame.Signal("pitch_position_error_deg");

            foreach (ComponentPayload component in frame.components ?? Array.Empty<ComponentPayload>())
            {
                if (component == null || !_byId.TryGetValue(component.id, out ComponentAvatar avatar))
                {
                    continue;
                }

                avatar.Apply(component);
                avatar.SetVibration(VibrationFor(component.id, nacelleVibration, gearboxVibration, windingTemp, pitchError));
            }
        }

        private static float VibrationFor(
            string componentId, float nacelle, float gearbox, float windingTemp, float pitchError)
        {
            switch (componentId)
            {
                case "gearbox":
                    return gearbox;
                case "main_bearing":
                    return nacelle;
                case "blade_set":
                    return nacelle;
                case "generator":
                    // No accelerometer channel in this PoC: approximate tremor from
                    // winding temperature so the generator still visibly protests.
                    return Mathf.Max(0f, windingTemp - 85f) * 0.12f;
                case "pitch_system":
                    return pitchError * 0.35f;
                default:
                    return 0f;
            }
        }

        private void ApplyRotor(TelemetryFrame frame)
        {
            if (_rotor == null)
            {
                return;
            }

            // The service integrates rotor azimuth, so the visual phase lines up
            // with the once-per-rev vibration signature instead of drifting.
            float azimuth = frame.Signal("rotor_angle_deg");
            float yaw = frame.environment != null ? frame.environment.yaw_deg : 0f;
            _rotor.localRotation = Quaternion.Euler(0f, yaw, azimuth);
        }

        private void ApplyBladeAttitude(TelemetryFrame frame)
        {
            if (_bladeSet == null || _bladeRestRotations.Length == 0)
            {
                return;
            }

            float pitchAngle = frame.Signal("pitch_angle_deg");
            float imbalance = frame.Signal("rotor_imbalance_index");
            float azimuth = frame.Signal("rotor_angle_deg");

            for (int i = 0; i < _blades.Count; i++)
            {
                // Pitch about the blade's own axis.
                _blades[i].localRotation = _bladeRestRotations[i] * Quaternion.Euler(pitchAngle, 0f, 0f);
            }

            // Imbalance flattens the rotor plane once per revolution.
            float flapping = imbalance * 6f * Mathf.Sin(azimuth * Mathf.Deg2Rad);
            _bladeSet.localRotation = Quaternion.Euler(flapping, 0f, 0f);
        }

        /// <summary>Worst avatar health, for the HUD and the alarm light.</summary>
        public float WorstHealth()
        {
            float worst = 1f;
            foreach (ComponentAvatar avatar in _avatars)
            {
                worst = Mathf.Min(worst, avatar.Health);
            }

            return worst;
        }

        /// <summary>Colour the status lamp by the worst component.</summary>
        public Color WorstColor()
        {
            return HealthPalette.ColorFor(WorstHealth());
        }
    }
}