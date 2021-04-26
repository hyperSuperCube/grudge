__copyright__ = """
Copyright (C) 2021 University of Illinois Board of Trustees
"""

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

import numpy as np
import numpy.linalg as la

from meshmode import _acf       # noqa: F401
from meshmode.dof_array import flatten, thaw
from meshmode.array_context import (  # noqa
        pytest_generate_tests_for_pyopencl_array_context
        as pytest_generate_tests)
import meshmode.mesh.generation as mgen

from pytools.obj_array import flat_obj_array, make_obj_array
import grudge.op as op

from grudge import DiscretizationCollection, sym, bind
import grudge.dof_desc as dof_desc

import pytest

import logging

logger = logging.getLogger(__name__)


# {{{ mass operator

@pytest.mark.parametrize("ambient_dim", [1, 2, 3])
@pytest.mark.parametrize("quad_tag", [dof_desc.QTAG_NONE, "OVSMP"])
def test_mass_mat_trig(actx_factory, ambient_dim, quad_tag):
    """Check the integral of some trig functions on an interval
    using the mass matrix.
    """
    actx = actx_factory()

    nelements = 17
    order = 4

    a = -4.0 * np.pi
    b = +9.0 * np.pi
    true_integral = 13*np.pi/2 * (b - a)**(ambient_dim - 1)

    from meshmode.discretization.poly_element import \
        QuadratureSimplexGroupFactory

    dd_quad = dof_desc.DOFDesc(dof_desc.DTAG_VOLUME_ALL, quad_tag)

    if quad_tag is dof_desc.QTAG_NONE:
        quad_tag_to_group_factory = {}
    else:
        quad_tag_to_group_factory = {
            quad_tag: QuadratureSimplexGroupFactory(order=2*order)
        }

    mesh = mgen.generate_regular_rect_mesh(
        a=(a,)*ambient_dim, b=(b,)*ambient_dim,
        n=(nelements,)*ambient_dim,
        order=1
    )
    dcoll = DiscretizationCollection(
        actx, mesh, order=order,
        quad_tag_to_group_factory=quad_tag_to_group_factory
    )

    def f(x):
        return actx.np.sin(x[0])**2

    volm_disc = dcoll.discr_from_dd(dof_desc.DD_VOLUME)
    x_volm = thaw(actx, volm_disc.nodes())
    f_volm = f(x_volm)
    ones_volm = volm_disc.zeros(actx) + 1

    quad_disc = dcoll.discr_from_dd(dd_quad)
    x_quad = thaw(actx, quad_disc.nodes())
    f_quad = f(x_quad)
    ones_quad = quad_disc.zeros(actx) + 1

    mop_1 = op.mass_operator(dcoll, dd_quad, f_quad)
    num_integral_1 = np.dot(actx.to_numpy(flatten(ones_volm)),
                            actx.to_numpy(flatten(mop_1)))

    err_1 = abs(num_integral_1 - true_integral)
    assert err_1 < 1e-9, err_1

    mop_2 = op.mass_operator(dcoll, dd_quad, ones_quad)
    num_integral_2 = np.dot(actx.to_numpy(flatten(f_volm)),
                            actx.to_numpy(flatten(mop_2)))

    err_2 = abs(num_integral_2 - true_integral)
    assert err_2 < 1.0e-9, err_2

# }}}


# {{{ mass operator on surface

def _ellipse_surface_area(radius, aspect_ratio):
    # https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.ellipe.html
    eccentricity = 1.0 - (1/aspect_ratio)**2

    if abs(aspect_ratio - 2.0) < 1.0e-14:
        # NOTE: hardcoded value so we don't need scipy for the test
        ellip_e = 1.2110560275684594
    else:
        from scipy.special import ellipe        # pylint: disable=no-name-in-module
        ellip_e = ellipe(eccentricity)

    return 4.0 * radius * ellip_e


def _spheroid_surface_area(radius, aspect_ratio):
    # https://en.wikipedia.org/wiki/Ellipsoid#Surface_area
    a = 1.0
    c = aspect_ratio

    if a < c:
        e = np.sqrt(1.0 - (a/c)**2)
        return 2.0 * np.pi * radius**2 * (1.0 + (c/a) / e * np.arcsin(e))
    else:
        e = np.sqrt(1.0 - (c/a)**2)
        return 2.0 * np.pi * radius**2 * (1 + (c/a)**2 / e * np.arctanh(e))


@pytest.mark.parametrize("name", [
    "2-1-ellipse", "spheroid", "box2d", "box3d"
    ])
def test_mass_surface_area(actx_factory, name):
    actx = actx_factory()

    # {{{ cases

    if name == "2-1-ellipse":
        from mesh_data import EllipseMeshBuilder
        builder = EllipseMeshBuilder(radius=3.1, aspect_ratio=2.0)
        surface_area = _ellipse_surface_area(builder.radius, builder.aspect_ratio)
    elif name == "spheroid":
        from mesh_data import SpheroidMeshBuilder
        builder = SpheroidMeshBuilder()
        surface_area = _spheroid_surface_area(builder.radius, builder.aspect_ratio)
    elif name == "box2d":
        from mesh_data import BoxMeshBuilder
        builder = BoxMeshBuilder(ambient_dim=2)
        surface_area = 1.0
    elif name == "box3d":
        from mesh_data import BoxMeshBuilder
        builder = BoxMeshBuilder(ambient_dim=3)
        surface_area = 1.0
    else:
        raise ValueError("unknown geometry name: %s" % name)

    # }}}

    # {{{ convergence

    from pytools.convergence import EOCRecorder
    eoc = EOCRecorder()

    for resolution in builder.resolutions:
        mesh = builder.get_mesh(resolution, builder.mesh_order)
        dcoll = DiscretizationCollection(actx, mesh, order=builder.order)
        volume_discr = dcoll.discr_from_dd(dof_desc.DD_VOLUME)

        logger.info("ndofs:     %d", volume_discr.ndofs)
        logger.info("nelements: %d", volume_discr.mesh.nelements)

        # {{{ compute surface area

        dd = dof_desc.DD_VOLUME
        ones_volm = volume_discr.zeros(actx) + 1
        mass_weights = op.mass_operator(dcoll, dd, ones_volm)
        approx_surface_area = np.dot(actx.to_numpy(flatten(ones_volm)),
                                     actx.to_numpy(flatten(mass_weights)))

        logger.info("surface: got {:.5e} / expected {:.5e}".format(
            approx_surface_area, surface_area))
        area_error = abs(approx_surface_area - surface_area) / abs(surface_area)

        # }}}

        h_max = bind(dcoll, sym.h_max_from_volume(dcoll.ambient_dim,
                                                  dim=dcoll.dim, dd=dd))(actx)
        eoc.add_data_point(h_max, area_error)

    # }}}

    logger.info("surface area error\n%s", str(eoc))

    assert eoc.max_error() < 3e-13 or eoc.order_estimate() > builder.order

# }}}


# vim: foldmethod=marker
