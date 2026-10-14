using System;
using UnityEngine;

namespace Vrar.Telemetry
{
    /// <summary>
    /// Plain-old-data mirror of one frame from <c>GET /api/telemetry</c>.
    /// Field names and types match the Python service exactly so
    /// <see cref="UnityEngine.JsonUtility"/> can deserialise without a converter.
    /// </summary>
    [Serializable]
    public class TelemetryFrame
    {
        public int schema_version;
        public int tick;
        public float elapsed_s;
        public string scenario;
        public bool healthy_asset;
        public EnvironmentPayload environment;
        public SignalPayload[] signals;
        public ComponentPayload[] components;

        public float Signal(string id)
        {
            if (signals == null)
            {
                return 0f;
            }

            foreach (SignalPayload signal in signals)
            {
                if (signal != null && signal.id == id)
                {
                    return signal.value;
                }
            }

            return 0f;
        }

        public ComponentPayload Component(string id)
        {
            if (components == null)
            {
                return null;
            }

            foreach (ComponentPayload component in components)
            {
                if (component != null && component.id == id)
                {
                    return component;
                }
            }

            return null;
        }

        /// <summary>Worst component health in the frame, 0..1.</summary>
        public float WorstHealth()
        {
            float worst = 1f;
            foreach (ComponentPayload component in components ?? Array.Empty<ComponentPayload>())
            {
                if (component != null)
                {
                    worst = Mathf.Min(worst, component.health);
                }
            }

            return worst;
        }
    }

    [Serializable]
    public class EnvironmentPayload
    {
        public float wind_speed_ms;
        public float ambient_temp_c;
        public float rotor_rpm;
        public float active_power_kw;
        public float yaw_deg;
    }

    [Serializable]
    public class SignalPayload
    {
        public string id;
        public float value;
        public string unit;
    }

    [Serializable]
    public class ComponentPayload
    {
        public string id;
        public string label;
        public float health;
        public string state;
        public float trend;
        public FactorPayload[] factors;

        /// <summary>Human-readable reason for the current score, built from the top factor.</summary>
        public string PrimaryReason()
        {
            if (factors == null || factors.Length == 0)
            {
                return "no measurable deviation";
            }

            FactorPayload top = factors[0];
            if (top == null || top.severity <= 0f)
            {
                return "all signals within envelope";
            }

            return $"{top.signal} {top.value:0.00} {top.unit} (warn {top.warn:0.00}, critical {top.critical:0.00})";
        }
    }

    [Serializable]
    public class FactorPayload
    {
        public string signal;
        public float value;
        public string unit;
        public float warn;
        public float critical;
        public float severity;
        public float weight;
        public float contribution;
    }
}